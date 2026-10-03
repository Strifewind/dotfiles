# Programmable completion, then readline behaviour
if ! shopt -oq posix; then
    if [ -f /usr/share/bash-completion/bash_completion ]; then
        . /usr/share/bash-completion/bash_completion
    elif [ -f /etc/bash_completion ]; then
        . /etc/bash_completion
    fi
fi
bind "set completion-ignore-case on"
bind "set show-all-if-ambiguous on"
bind "set bell-style none"
bind "set colored-stats on"
bind "set visible-stats on"
