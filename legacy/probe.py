import subprocess, time, Quartz, mss, numpy as np, sys

subprocess.run(["open","-a","/Users/ruggsea/Library/Application Support/Steam/steamapps/common/Nidhogg/Nidhogg.app"])
time.sleep(8)

wins = Quartz.CGWindowListCopyWindowInfo(
    Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
    Quartz.kCGNullWindowID)
for w in wins:
    owner = w.get('kCGWindowOwnerName'); name = w.get('kCGWindowName')
    b = w.get('kCGWindowBounds')
    if 'Nidhogg' in str(owner) or 'Nidhogg' in str(name):
        print("WINDOW:", owner, "|", name, "|", b)

# pick the game window
gm = [w for w in wins if 'nidhogg' in str(w.get('kCGWindowOwnerName','')).lower()]
if not gm:
    print("NO NIDHOGG WINDOW FOUND"); sys.exit(1)
b = gm[0]['kCGWindowBounds']
grab = {"left": int(b['X']), "top": int(b['Y']), "width": int(b['Width']), "height": int(b['Height'])}
print("GRAB:", grab)

with mss.mss() as sct:
    t0 = time.perf_counter(); n = 60
    for _ in range(n):
        img = np.asarray(sct.grab(grab))
    dt = time.perf_counter() - t0
    print(f"capture: {n/dt:.1f} fps  shape={img.shape}")
    mss.tools.to_png(img[:,:,:3].tobytes(), (img.shape[1], img.shape[0]), output="frame0.png")
    print("unique colors in center row:", len(np.unique(img[img.shape[0]//2,:,:3], axis=0)))
