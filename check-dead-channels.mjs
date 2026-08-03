name: Daily Playlist Update (Clean + Check + Commit)

on:
  schedule:
    - cron: '0 0 * * *'
  workflow_dispatch:

permissions:
  contents: write

concurrency:
  group: playlist-write
  cancel-in-progress: false

jobs:
  update-playlist:
    runs-on: ubuntu-latest
    timeout-minutes: 45
    steps:
      - name: Checkout Code
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'

      - name: Set up Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '20'

      - name: Clean & categorize playlist
        run: python build_playlist.py --overwrite

      - name: Remove dead channels
        run: node check-dead-channels.mjs

      - name: Commit and Push Changes
        run: |
          git config --local user.email "action@github.com"
          git config --local user.name "GitHub Action"
          git add playlist.m3u
          git commit -m "Daily update: clean, categorize, remove dead channels [skip ci]" || exit 0
          git push
