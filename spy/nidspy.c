// Injected into the game: dumps its own memory on request. No ptrace, no permissions.
#define _GNU_SOURCE
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <unistd.h>

static int g_pid;

static void *loop(void *arg) {
    char cmd[64], res[64];
    snprintf(cmd, sizeof cmd, "/tmp/nid_cmd_%d", g_pid);
    snprintf(res, sizeof res, "/tmp/nid_res_%d", g_pid);
    for (;;) {
        usleep(50000);
        FILE *f = fopen(cmd, "r");
        if (!f) continue;
        char line[512];
        while (fgets(line, sizeof line, f)) {
            unsigned long a, l;
            char out[256];
            if (sscanf(line, "dump %lx %lx %255s", &a, &l, out) == 3) {
                FILE *o = fopen(out, "wb");
                if (o && fwrite((void *)a, 1, l, o) == l) { fclose(o); }
                else if (o) { fclose(o); unlink(out); }
            } else if (!strncmp(line, "poke ", 5)) {
                unsigned long a, i = 0; char hex[512];
                char *p = line + 5;
                a = strtoul(p, &p, 16);
                char *h = strchr(p, ' ');
                if (h) {
                    for (; *h && i < sizeof hex - 1; h++) {
                        if ((*h >= '0' && *h <= '9') || (*h >= 'a' && *h <= 'f')) hex[i++] = *h;
                    }
                    hex[i] = 0;
                    for (unsigned long k = 0; k + 1 < i; k += 2) {
                        unsigned int byte;
                        sscanf(hex + k, "%2x", &byte);
                        ((unsigned char *)a)[k / 2] = (unsigned char)byte;
                    }
                }
            } else if (!strncmp(line, "ping", 4)) {
                FILE *o = fopen(res, "w");
                if (o) { fprintf(o, "pong %d\n", g_pid); fclose(o); }
            }
        }
        fclose(f);
        unlink(cmd);
    }
    return NULL;
}

__attribute__((constructor)) static void boot(void) {
    prctl(PR_SET_PTRACER, PR_SET_PTRACER_ANY, 0, 0, 0);
    g_pid = getpid();
    pthread_t t;
    pthread_create(&t, NULL, loop, NULL);
}
