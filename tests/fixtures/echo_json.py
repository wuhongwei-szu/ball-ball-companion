# Echo only: no send modules, production config, or network imports.
import json
from pathlib import Path
import sys
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from text_input import read_json_text
print(json.dumps(read_json_text(many=sys.argv[1] == 'many'), ensure_ascii=True))
