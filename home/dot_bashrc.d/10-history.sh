# History: large, timestamped, de-duplicated, shared live between panes
HISTSIZE=50000
HISTFILESIZE=100000
HISTCONTROL=ignoreboth:erasedups
HISTTIMEFORMAT="%Y-%m-%d %H:%M  "
HISTIGNORE="ls:ll:la:cd:cd -:pwd:exit:clear:history"
shopt -s histappend cmdhist
# Write each command at once and read the others' — every tmux pane sees them.
# 20-prompt.sh puts its prompt function in front of this.
PROMPT_COMMAND="history -a; history -c; history -r"
