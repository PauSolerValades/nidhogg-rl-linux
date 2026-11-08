// Injected into the game: dumps its own memory on request. No ptrace, no permissions.
#define _GNU_SOURCE
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <time.h>
#include <unistd.h>

static int g_pid;

static void *loop(void *arg) {
    char cmd[64], res[64], cmd_done[80];
    snprintf(cmd, sizeof cmd, "/tmp/nid_cmd_%d", g_pid);
    snprintf(res, sizeof res, "/tmp/nid_res_%d", g_pid);
    snprintf(cmd_done, sizeof cmd_done, "/tmp/nid_cmd_%d.done", g_pid);
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
            } else if (!strncmp(line, "add ", 4)) {
                // add <addr> <delta-hex> <ms>: ACCUMULATE. Physics can rewrite a constant
                // every tick; it cannot ignore a value that keeps running away.
                unsigned long a, ms; char hex[64];
                if (sscanf(line + 4, "%lx %63s %lu", &a, hex, &ms) == 3) {   /* addr hex ms */
                    unsigned long nb = strlen(hex) / 2;
                    struct timespec t0, t1;
                    clock_gettime(CLOCK_MONOTONIC, &t0);
                    do {
                        if (nb == 4) {
                            float d; unsigned int u = 0;
                            sscanf(hex, "%8x", &u); memcpy(&d, &u, 4);
                            *(float *)(void *)a += d;
                        } else if (nb == 8) {
                            double d; unsigned long long u = 0;
                            sscanf(hex, "%16llx", &u); memcpy(&d, &u, 8);
                            *(double *)(void *)a += d;
                        }
                        usleep(500);
                        clock_gettime(CLOCK_MONOTONIC, &t1);
                    } while ((unsigned long)((t1.tv_sec - t0.tv_sec) * 1000 +
                                             (t1.tv_nsec - t0.tv_nsec) / 1000000) < ms);
                }
            } else if (!strncmp(line, "hold ", 5)) {
                // hold <addr> <bytes-hex> <ms>: pin a value across frames so the
                // game cannot overwrite it before we observe the effect.
                unsigned long a, ms; char hex[64];
                if (sscanf(line + 5, "%lx %63s %lu", &a, hex, &ms) == 3) {   /* addr hex ms */
                    unsigned char buf[32];
                    unsigned long nb = strlen(hex) / 2;
                    if (nb > sizeof buf) nb = sizeof buf;
                    for (unsigned long k = 0; k < nb; k++) {
                        unsigned int b;
                        sscanf(hex + k * 2, "%2x", &b);
                        buf[k] = (unsigned char)b;
                    }
                    struct timespec t0, t1;
                    clock_gettime(CLOCK_MONOTONIC, &t0);
                    do {
                        memcpy((void *)a, buf, nb);
                        usleep(500);
                        clock_gettime(CLOCK_MONOTONIC, &t1);
                    } while ((unsigned long)((t1.tv_sec - t0.tv_sec) * 1000 +
                                             (t1.tv_nsec - t0.tv_nsec) / 1000000) < ms);
                }
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
        /* Drain loses a command written while we were reading it: unlink() deletes the new
           file. Rename ours away and delete *that*, so a fresh write survives to the next
           poll. (Worker W measured lost poke/hold commands without this.) */
        if (rename(cmd, cmd_done) == 0) unlink(cmd_done);
        else unlink(cmd);
    }
    return NULL;
}

__attribute__((constructor)) static void boot(void) {
    prctl(PR_SET_PTRACER, PR_SET_PTRACER_ANY, 0, 0, 0);
    g_pid = getpid();
    pthread_t t;
    pthread_create(&t, NULL, loop, NULL);
}
