# Small shell functions

mkcd() { mkdir -p "$1" && cd "$1" || return; }     # make a directory and enter it

up() {                                             # up N: go up N directories
    local count="${1:-1}" path="" i
    for ((i = 0; i < count; i++)); do path+="../"; done
    cd "$path" || return 1
}

extract() {                                        # one command for any archive
    if [ ! -f "$1" ]; then echo "'$1' is not a file"; return 1; fi
    case "$1" in
        *.tar.bz2) tar xjf "$1" ;;
        *.tar.gz)  tar xzf "$1" ;;
        *.tar.xz)  tar xJf "$1" ;;
        *.bz2)     bunzip2 "$1" ;;
        *.rar)     unrar x "$1" ;;
        *.gz)      gunzip "$1" ;;
        *.tar)     tar xf "$1" ;;
        *.tbz2)    tar xjf "$1" ;;
        *.tgz)     tar xzf "$1" ;;
        *.zip)     unzip "$1" ;;
        *.Z)       uncompress "$1" ;;
        *.7z)      7z x "$1" ;;
        *)         echo "'$1' — unknown archive format"; return 1 ;;
    esac
}

# docker shortcuts
dk()     { docker "$@"; }
dkc()    { docker compose "$@"; }
dkps()   { docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'; }
dklogs() { docker logs -f --tail=100 "$1"; }

# tmux window helpers
tn() { tmux new-window -n "${1:-scratch}"; }
ts() { tmux split-window -h; }
