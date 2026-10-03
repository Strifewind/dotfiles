# dotfiles

Shell, Emacs, tmux and git configuration, managed with [chezmoi](https://www.chezmoi.io/).

Each machine picks a **profile** the first time it is set up:

| profile | gets |
|---|---|
| `server` | everything, tmux auto-attach on by default, an Emacs systemd user unit |
| `workstation` | everything except tmux |
| `general` | everything except the Emacs unit; tmux auto-attach asked at setup |

## Install (no root needed)

```sh
sh -c "$(curl -fsLS get.chezmoi.io)" -- -b "$HOME/.local/bin"
~/.local/bin/chezmoi init https://github.com/Strifewind/dotfiles.git
~/.local/bin/chezmoi diff      # read before applying
~/.local/bin/chezmoi apply
```

Anything machine-specific goes in `~/.bashrc.d/99-local.sh`, which chezmoi never touches.
After install, `dots help` lists the day-to-day commands.

## This repo is public

`.githooks/leakcheck` runs on every commit (pre-commit and commit-msg) and in CI. It
blocks private addresses, internal hostnames, email addresses and commits made with
anything but the identity in `.git-public-identity`. Personal material belongs in a
separate private repository, not here.
