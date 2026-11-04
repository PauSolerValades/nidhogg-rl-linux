"""Drive Nidhogg into a Training match, deciding purely from what's on screen:
the number of menu rows tells us which menu we're in."""
import time
import nav

MAIN, SP_SUB, PERSONALITY = 5, 2, 8


def current(img):
    rows = nav.menu_rows(img)
    return len(rows), nav.selected_index(img)[0]


def press(code, wait=1.0):
    nav.press(code, wait)


def enter_match(timeout=60):
    t0 = time.time()
    last = None
    while time.time() - t0 < timeout:
        img = nav.capture()
        if img is None:
            time.sleep(0.5)
            continue
        n, sel = current(img)
        if n != last and n > 0:
            print(f"  screen with {n} rows, selected {sel}")
            last = n
        if n == 1:
            press(13, 1.6)            # title screen: "PRESS ENTER"
        elif n == MAIN:
            if sel == 4:              # QUIT TO DESKTOP - never press enter here
                nav.press(38, 0.6)
                continue
            if sel != 0:
                nav.goto_item(0)
            press(13, 1.4)
        elif n == SP_SUB:
            nav.goto_item(1)          # ARCADE(0), TRAINING(1)
            press(13, 1.4)
        elif n == PERSONALITY:
            nav.goto_item(0)          # easiest personality
            press(13, 2.5)
            return True
        else:
            time.sleep(0.6)
    return False


if __name__ == "__main__":
    print("enter_match:", enter_match())
    time.sleep(2)
