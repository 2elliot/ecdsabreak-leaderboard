# Circuit competition leaderboard

The page at https://leaderboard.taroreh.com. Every 5 minutes, a GitHub Action runs `standings.py` against the public board and renders the result with `build.py`. It uses no keys and writes nothing to the board.

`standings.py` is the competition's own reader, copied unchanged, and the workflow passes the close with `--close`. Notes aren't checked here, because they live in the bot's archive, so the operator's final table decides.

```sh
python3 -I test_build.py
python3 -I standings.py https://ecdsabreak.taroreh.com --close 2026-11-13T07:59:00 --cache status-cache.json --json standings.json
python3 -I build.py standings.json site/index.html
```
