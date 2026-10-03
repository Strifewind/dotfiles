# Shell behaviour
shopt -s checkwinsize      # update LINES/COLUMNS after each command
shopt -s cdspell dirspell  # forgive small typos in directory names
shopt -s autocd            # type a directory name to cd into it
shopt -s globstar          # ** matches recursively
shopt -s nocaseglob        # case-insensitive globbing
set -o noclobber           # > won't overwrite a file; use >| when you mean it
