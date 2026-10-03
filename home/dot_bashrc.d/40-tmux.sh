# Attach to tmux on SSH login — only when this machine said yes at setup
# (tmux_autoattach) and only when it is safe to.
[ "${DOT_TMUX_AUTOATTACH:-0}" = 1 ] || return 0
[[ $- == *i* ]]                     || return 0   # interactive shells only: scp/rsync/git-over-ssh skip
[ -t 0 ] && [ -t 1 ]                || return 0   # needs a real terminal
[ -n "${SSH_CONNECTION:-}" ]        || return 0   # SSH logins only (never local terminal tabs)
[ -z "${TMUX:-}" ]                  || return 0   # already inside tmux on this machine
case "${TERM:-}" in tmux*|screen*) return 0 ;; esac   # arrived from tmux elsewhere: no nesting
[ "${TERM_PROGRAM:-}" != vscode ]   || return 0   # VS Code Remote-SSH terminals
command -v tmux >/dev/null 2>&1     || return 0
tmux new-session -A -s main                       # detaching drops you to a plain shell
