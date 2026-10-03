# Prompt and colours, chosen by $DOT_PROFILE (set in 00-env.sh):
#   server       vivid, two lines, git ahead/behind, time
#   workstation  muted pastel, one line
#   general      the vivid layout with an orchid host name, so a school or
#                borrowed machine never looks like the server at a glance

export CLICOLOR=1
export PAGER="less"
export LESS="-R --quit-if-one-screen --ignore-case --status-column --LONG-PROMPT --RAW-CONTROL-CHARS --HILITE-UNREAD --tabs=4 --no-init --window=-4"

_pc_reset='\[\e[0m\]'

# Text from git goes into PS1 by reference (\${_ps1_git}), never pasted in: PS1 is
# expanded again at display time, and a branch name may contain $( ) or `.

case "${DOT_PROFILE:-general}" in
workstation)
    export GREP_COLORS='ms=01;34:mc=01;34:sl=:cx=:fn=35:ln=32:bn=32:se=36'
    export LS_COLORS='di=0;34:ln=0;36:so=0;35:pi=0;33:ex=0;32:bd=0;34:cd=0;34:su=0;34:sg=0;34:tw=0;34:ow=0;34'
    export LESS_TERMCAP_mb=$'\e[1;34m' LESS_TERMCAP_md=$'\e[1;34m' LESS_TERMCAP_me=$'\e[0m'
    export LESS_TERMCAP_se=$'\e[0m' LESS_TERMCAP_so=$'\e[38;5;110m' LESS_TERMCAP_ue=$'\e[0m'
    export LESS_TERMCAP_us=$'\e[4;38;5;108m'

    _pc_host='\[\e[38;5;110m\]'     # muted steel blue
    _pc_sep='\[\e[38;5;240m\]'      # dark gray
    _pc_path='\[\e[38;5;108m\]'     # sage green
    _pc_git='\[\e[38;5;139m\]'      # soft purple
    _pc_symbol='\[\e[38;5;67m\]'    # slate blue
    _pc_error='\[\e[38;5;167m\]'    # muted red

    _git_branch() {
        local branch
        branch=$(git symbolic-ref --short HEAD 2>/dev/null) ||
            branch=$(git rev-parse --short HEAD 2>/dev/null)
        [ -n "$branch" ] && printf ' [%s]' "$branch"
    }

    # user@host · ~/path [branch] ✕1
    # ›
    _set_ps1() {
        local code=$? err=""
        [ "$code" -ne 0 ] && err="${_pc_error} ✕${code}${_pc_reset}"
        _ps1_git=$(_git_branch)
        PS1="${_pc_host}\u@\h${_pc_sep} · ${_pc_path}\w${_pc_git}\${_ps1_git}${err}${_pc_reset}\n${_pc_symbol}›${_pc_reset} "
    }
    ;;
*)
    export GREP_COLORS='ms=01;36:mc=01;36:sl=:cx=:fn=33:ln=32:bn=32:se=36'
    export LS_COLORS='di=1;34:ln=1;36:so=1;35:pi=1;33:ex=1;32:bd=1;34:cd=1;34:su=1;31:sg=1;31:tw=1;34:ow=1;34'
    export LESS_TERMCAP_mb=$'\e[1;36m' LESS_TERMCAP_md=$'\e[1;36m' LESS_TERMCAP_me=$'\e[0m'
    export LESS_TERMCAP_se=$'\e[0m' LESS_TERMCAP_so=$'\e[38;5;39m' LESS_TERMCAP_ue=$'\e[0m'
    export LESS_TERMCAP_us=$'\e[4;38;5;82m'

    if [ "${DOT_PROFILE:-}" = server ]; then
        _pc_host='\[\e[38;5;39m\]'  # vivid blue
    else
        _pc_host='\[\e[38;5;170m\]' # orchid — not the server
    fi
    _pc_bracket='\[\e[38;5;240m\]'  # dark gray structure
    _pc_sep='\[\e[38;5;240m\]'
    _pc_path='\[\e[38;5;82m\]'      # bright green
    _pc_git='\[\e[38;5;214m\]'      # amber
    _pc_time='\[\e[38;5;244m\]'     # muted gray
    _pc_venv='\[\e[38;5;75m\]'      # sky blue
    _pc_symbol='\[\e[38;5;208m\]'   # orange
    _pc_error='\[\e[38;5;196m\]'    # red

    _git_info() {   # branch, * unstaged, + staged, ↑ahead ↓behind
        local branch dirty="" info="" counts behind ahead
        branch=$(git symbolic-ref --short HEAD 2>/dev/null) ||
            branch=$(git rev-parse --short HEAD 2>/dev/null) || return
        git diff --quiet 2>/dev/null || dirty="*"
        git diff --cached --quiet 2>/dev/null || dirty="${dirty}+"
        counts=$(git rev-list --left-right --count "@{upstream}...HEAD" 2>/dev/null)
        if [ -n "$counts" ]; then
            behind=${counts%%[[:space:]]*}; ahead=${counts##*[[:space:]]}
            [ "$behind" -gt 0 ] && info+=" ↓${behind}"
            [ "$ahead" -gt 0 ] && info+=" ↑${ahead}"
        fi
        printf '%s%s%s' "$branch" "$dirty" "$info"
    }

    # ┌─ user@host  ~/path [branch*+ ↑1] (venv) ✕1  HH:MM
    # └─ ❯
    _set_ps1() {
        local code=$? err=""
        _ps1_git=$(_git_info); [ -n "$_ps1_git" ] && _ps1_git=" [$_ps1_git]"
        _ps1_venv=""; [ -n "${VIRTUAL_ENV:-}" ] && _ps1_venv=" ($(basename "$VIRTUAL_ENV"))"
        [ "$code" -ne 0 ] && err=" ${_pc_error}✕${code}${_pc_reset}"
        PS1="${_pc_bracket}┌─${_pc_reset} ${_pc_host}\u@\h${_pc_reset}${_pc_sep}  ${_pc_path}\w${_pc_reset}${_pc_git}\${_ps1_git}${_pc_venv}\${_ps1_venv}${_pc_reset}${err}${_pc_sep}  ${_pc_time}\A${_pc_reset}\n${_pc_bracket}└─${_pc_reset} ${_pc_symbol}❯${_pc_reset} "
    }
    ;;
esac

# The prompt function must run first, so it still sees the last command's exit code.
PROMPT_COMMAND="_set_ps1${PROMPT_COMMAND:+; $PROMPT_COMMAND}"
