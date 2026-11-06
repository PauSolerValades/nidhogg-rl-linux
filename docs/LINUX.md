# Running the real game headless on Linux (Proton)

Measured on this machine (8 cores, Intel UHD 620 + MX150, btrfs). Everything below is
numbers from `farm.sh`, not estimates.

## What works

| Thing | How | Result |
|---|---|---|
| No window on screen | `Xvfb :N` per instance, game gets `DISPLAY=:N` | works, nothing visible |
| No Steam client needed | `proton waitforexitandrun Nidhogg.exe` + `SteamAppId=94400` | runs, no Steam login |
| Silent | `[Software\\Wine\\Drivers] "Audio"=""` in the prefix `user.reg` | 0 audio threads, 0 pulse sink-inputs |
| Faster | patch GEN8 window size `960x600` → `320x200` in a **copy** of `data.win` | 25 fps → **60 fps** |
| Cheap | same patch | **112% → 41%** CPU per instance |
| Isolated | one reflinked prefix per instance (`cp -a --reflink=always`) | no prefix-lock fights |
| Keyboard in | `xdotool windowfocus $win` + `xdotool key`, **no window manager needed** | title screen reacts |
| Playable at 320x200 | room space is 320x200 internally, window size is just scaling | renders correctly |

The window-size patch is config, not gameplay: `data.win` GEN8 header field at offset
`0x10 + 60` (DefaultWindowWidth/Height). The original install is never modified — the farm
runs from a reflink copy in `~/.nidfarm/game`.

## Cost per instance @ 320×200

* ~40–56% of one core (render thread, `dxvk-submit`/`wined3d_cs` dominated)
* ~455 MB RSS
* 60 steps/s (the game's own speed cap — unchanged by all of the above)

→ 8 cores ≈ 14 instances ≈ **840 steps/s**. A 16-core/32 GB server ≈ 28 instances ≈ 1700 steps/s.
For comparison, the macOS harness topped out at 23.8 fps on **one** instance.

## Not done yet

1. **State read on Linux.** The macOS harness used an injected dylib + runner API. Here:
   `/proc/<pid>/mem` from outside, no injection. Same information, less machinery.
2. **Entry sequence.** The 7-key training entry (`13, W, 13, S, S, 13, 13, 13`) is untested
   here; it costs ~10–15 s of wall clock per episode at 60 fps.
3. **Actual step-rate verification.** fps above is measured by distinct frames via
   `ffmpeg -vf mpdecimate`; true steps/s comes from position deltas once (1) exists.
4. **Speed above 60.** Game speed is not in GEN8/OPTN; room `speed` fields are 0. Unknown
   where this build stores it. Parallelism makes this optional.

## Usage

```bash
./farm.sh init      # reflink game copy + 320x200 patch + wine prefix template (audio off)
./farm.sh start 8   # 8 instances on :10..:17, one prefix each
./farm.sh status
./farm.sh stop
```
