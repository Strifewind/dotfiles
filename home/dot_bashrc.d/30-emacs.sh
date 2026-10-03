# Emacs: always go through the daemon.
command -v emacsclient >/dev/null 2>&1 || return 0
e() { emacsclient -nw -a '' "$@"; }            # starts the daemon if none is running
alias eq='emacsclient -e "(kill-emacs)"'
export EDITOR="emacsclient -nw -a emacs"       # -a emacs, not '': some tools split EDITOR on spaces
export VISUAL="$EDITOR"
