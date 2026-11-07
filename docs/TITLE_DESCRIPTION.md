(0) Developer and music - tells the developer and composer. in 10 seconds goes to (1)
(1) Title screen - Just Nidhogg and press enter.
  - If some time passes without input, a sample match gets loaded.
(2) Title screen background match - The Nidhogg title but with a CPU played match on the backround.
  - If enter gets pressed, its (1)
  - if nothing gets pressed, the match gets played, and after some time it or if one of the CPU wins it goes to (2)
(3) Menu - Cycle between with up in order or down the other way around: Multiplayer -> Single Player -> News -> Quit to desktop -> extras -> options
  - Pressing the name, goes to the appropiatename.
(4) Multiplier - two options, cycle with up and down: local -> multiplier.
(5) Single Player - two options, cycle with up and down: arcade -> online.
...
(10) Multiplier, local: Spawns the two characters with a wall separating them, yellow left, orange right. both must up a platform with the proper color, yellow to the left and orange to the right.
  - When both are in their respective platforms, it spawns the screen selection (11).
(11) Stage Selection - This is a small state machine in itself, as the position to the next one depends on the current position.
  (11a) Castle - if enter, moves to the game

(23) Game Start: characters cannot move, one must kill each other. When the character advanced left (22) and right (24)
  (22) Middle Left: Left (21), Right (23)
  (21) Final Left: Left (20), Right (21)
  (20) Won Left - when eaten foest to 27
  (24) Middle Right: Left (23), Right (24)
  (25) Final Right: Left (25), Left (20)
  (26) Won Right - when eaten, goes to 27
(27) End - Says who won.
  - If 10 secons pass or enter is pressed, goes to (10)
