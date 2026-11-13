import base64
import io
import logging
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
import wave

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
import listen_audio as audio


class AudioTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=TOOLS.parent, prefix='synthetic-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def wav(self):
        output = io.BytesIO()
        with wave.open(output, 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(24000)
            wav.writeframes(bytes(range(128)) * 200)
        path = self.root / 'voice.wav'
        path.write_bytes(output.getvalue())
        return path

    def test_api_receives_entire_audio_not_only_a_transcript(self):
        path = self.wav()
        client = Mock()
        client.chat.completions.create.return_value = types.SimpleNamespace(
            choices=[types.SimpleNamespace(finish_reason='stop', message=types.SimpleNamespace(content='语速较慢，中间有停顿。'))])
        result = audio.analyze(path, client)
        args = client.chat.completions.create.call_args.kwargs
        part = args['messages'][1]['content'][0]['input_audio']
        self.assertEqual(base64.b64decode(part['data']), path.read_bytes())
        self.assertEqual(part['format'], 'wav')
        self.assertEqual(args['modalities'], ['text'])
        self.assertFalse(args['store'])
        self.assertTrue(result['whole_recording'])

    def test_silk_decoding_keeps_all_pcm_including_silence_and_pauses(self):
        path = self.root / 'voice.silk'
        path.write_bytes(b'\x02#!SILK_V3\nfixture')
        pcm = b'\0\0' * 24000 + b'\x01\x00' * 24000
        decoder = types.SimpleNamespace(decode=lambda source, output, rate: output.write(pcm))
        with patch.dict(sys.modules, {'pysilk': decoder}):
            result, fmt = audio.prepare_audio(path)
        with wave.open(io.BytesIO(result), 'rb') as wav:
            self.assertEqual(wav.getframerate(), 24000)
            self.assertEqual(wav.getnframes(), 48000)
            self.assertEqual(wav.readframes(48000), pcm)
        self.assertEqual(fmt, 'wav')

    def test_oversized_input_is_rejected_without_api_call(self):
        path = self.root / 'large.wav'
        path.write_bytes(b'x' * 101)
        client = Mock()
        with patch.object(audio, 'MAX_INPUT_BYTES', 100), self.assertRaises(ValueError):
            audio.analyze(path, client)
        client.chat.completions.create.assert_not_called()

    def test_incomplete_wav_is_rejected_before_api(self):
        path = self.wav()
        path.write_bytes(path.read_bytes()[:-128])
        client = Mock()
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            audio.analyze(path, client)
        client.chat.completions.create.assert_not_called()

    def test_truncated_or_refused_analysis_is_not_a_success(self):
        for reason, refusal in [('length', None), ('content_filter', None), ('stop', 'unavailable')]:
            with self.subTest(reason=reason, refusal=refusal):
                client = Mock()
                client.chat.completions.create.return_value = types.SimpleNamespace(choices=[
                    types.SimpleNamespace(finish_reason=reason, message=types.SimpleNamespace(
                        content='这只是部分结论', refusal=refusal))])
                with self.assertRaises(RuntimeError):
                    audio.analyze(self.wav(), client)
                self.assertEqual(client.chat.completions.create.call_count, 1)

    def test_decoder_output_limit_rejects_instead_of_truncating(self):
        with patch.object(audio, 'MAX_PCM_BYTES', 4):
            output = audio.BoundedPCM()
            output.write(b'1234')
            with self.assertRaises(ValueError):
                output.write(b'5')
            self.assertEqual(output.getvalue(), b'1234')

    def test_sdk_debug_logs_do_not_capture_recording_body(self):
        import httpx
        from openai import OpenAI
        output = io.StringIO()
        logger = logging.getLogger('openai._base_client')
        old_level, old_disabled = logger.level, logger.disabled
        handler = logging.StreamHandler(output)
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.disabled = False
        self.addCleanup(logger.removeHandler, handler)
        self.addCleanup(logger.setLevel, old_level)
        self.addCleanup(setattr, logger, 'disabled', old_disabled)
        client = OpenAI(api_key='offline-fixture', base_url='https://offline.invalid/v1',
                        max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(
                            lambda request: httpx.Response(400, json={'error': {'message': 'fixture'}}))))
        with self.assertRaises(Exception):
            audio.analyze(self.wav(), client)
        self.assertEqual(output.getvalue(), '')
        self.assertEqual(logger.level, logging.DEBUG)
        self.assertFalse(logger.disabled)


if __name__ == '__main__':
    unittest.main()
