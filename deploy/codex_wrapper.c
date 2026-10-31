/*
 * Tiny forwarder for cc-connect.
 *
 * cc-connect v1.3.3 resolves the Codex CLI via PATH, but the MSIX
 * WindowsApps directory cannot be enumerated, so the real codex.exe
 * cannot be placed on PATH directly. This wrapper is a normal,
 * listable executable that forwards to the real CLI.
 *
 * The launcher sets CC_CODEX_REAL to the current MSIX codex.exe path.
 */
#include <process.h>
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char *argv[]) {
    const char *real = getenv("CC_CODEX_REAL");
    if (real == NULL || real[0] == '\0') {
        fprintf(stderr, "codex wrapper: CC_CODEX_REAL is not set\n");
        return 127;
    }

    char **args = (char **)malloc(sizeof(char *) * (size_t)(argc + 1));
    if (args == NULL) {
        fprintf(stderr, "codex wrapper: out of memory\n");
        return 126;
    }
    for (int i = 0; i < argc; i++) {
        args[i] = argv[i];
    }
    args[0] = (char *)real;
    args[argc] = NULL;

    int rc = _spawnv(_P_WAIT, real, (const char *const *)args);
    free(args);
    if (rc == -1) {
        perror("codex wrapper: spawn failed");
        return 127;
    }
    return rc;
}
