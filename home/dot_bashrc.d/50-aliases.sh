# Aliases — the union of what the server and workstations had

# navigation
alias ..='cd ..'
alias ...='cd ../..'
alias ....='cd ../../..'

# ls — GNU or BSD
if ls --color=auto /dev/null >/dev/null 2>&1; then
    alias ls='ls --color=auto -F'
else
    alias ls='ls -GF'
fi
alias ll='ls -lh'
alias la='ls -lAh'
alias lt='ls -lhtr'          # by time, oldest first
alias lsize='ls -lhS'        # by size

# safety nets
alias rm='rm -I'             # ask once before removing 3+ files
alias cp='cp -i'
alias mv='mv -i'

# readable output
alias grep='grep --color=auto'
alias rg='rg --color=always'
alias df='df -h'
alias du='du -h'
alias du1='du -hd1'          # one level deep (plain du -hd1 would break du -sh)
alias free='free -h'
alias jobs='jobs -l'

# tmux
alias t='tmux'
alias ta='tmux attach -t'
alias tl='tmux list-sessions'

# git
alias gs='git status -sb'
alias gd='git diff'
alias gl='git log --oneline --graph --decorate -20'
alias gp='git push'
alias gf='git fetch --all --prune'
