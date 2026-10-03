;;; init.el --- shared Emacs configuration -*- lexical-binding: t; -*-

;; =============================================================================
;; init.el — managed by chezmoi (dotfiles core, public). Edit it in place; it is
;; a symlink into the repo. Do not put host names, addresses or secrets here:
;; host-specific settings go in private.el (private repo), loaded at the end.
;;
;; Philosophy: no frameworks, understand what each line does
;; Aesthetic:  FiraCode + ligatures, Dark++ / Monokai inspired colors
;;
;; First-time setup on a new machine (needs internet once):
;;   emacs --batch -l ~/.emacs.d/init.el   ; installs all packages, then exits
;; =============================================================================

;; =============================================================================
;; STARTUP
;; =============================================================================

(setq gc-cons-threshold (* 100 1024 1024))
(add-hook 'emacs-startup-hook
          (lambda () (setq gc-cons-threshold (* 2 1024 1024))))

(setq native-comp-async-report-warnings-errors nil)
(setq byte-compile-warnings '(not obsolete))

(setq inhibit-startup-screen t)
(setq inhibit-startup-echo-area-message t)
(setq initial-scratch-message nil)

;; =============================================================================
;; MACHINE AND PROFILE
;;
;; my/machine  the short hostname, lowercase — the same id hosts.yaml and `dots`
;;             use. Not WSL_DISTRO_NAME: every stock WSL install is "Ubuntu".
;; my/profile  server | workstation | general, chosen when the dotfiles were set
;;             up. Read from a file, because an Emacs daemon started by systemd
;;             never sees the shell's DOT_PROFILE variable.
;; Check with:  M-: (list my/machine my/profile) RET
;; =============================================================================

(require 'subr-x)

(defvar my/machine (downcase (car (split-string (system-name) "\\.")))
  "Short hostname of this machine, lowercase.")

(defvar my/profile
  (let ((f (expand-file-name "~/.config/dotfiles/profile")))
    (or (and (file-readable-p f)
             (let ((p (string-trim (with-temp-buffer
                                     (insert-file-contents f)
                                     (buffer-string)))))
               (and (not (string-empty-p p)) p)))
        "general"))
  "Dotfiles profile of this machine: \"server\", \"workstation\" or \"general\".")

(defun my/profile-p (&rest profiles)
  "Non-nil if this machine's profile is one of PROFILES."
  (member my/profile profiles))

(defun my/machine-p (name)
  "Non-nil if this machine's id is NAME (case-insensitive). Used by private.el."
  (string= my/machine (downcase name)))

;; =============================================================================
;; PACKAGE MANAGEMENT
;; =============================================================================

(require 'package)
(setq package-archives
      '(("melpa"  . "https://melpa.org/packages/")
        ("gnu"    . "https://elpa.gnu.org/packages/")
        ("nongnu" . "https://elpa.nongnu.org/nongnu/")))

(package-initialize)

;; --- Packages compiled by a different Emacs -----------------------------------
;; Packages are byte-compiled by whichever Emacs installed them, and some bake in
;; version checks at compile time (marginalia, through compat). Run them under
;; another major version (apt 29 -> snap 31, or a snap auto-refresh to a new major)
;; and they fail with errors like "void-function
;; marginalia--orig-completion-metadata-get". So remember which major version
;; built ~/.emacs.d/elpa and recompile everything once when it changes.
(defvar my/elpa-stamp (expand-file-name ".built-with-emacs" package-user-dir)
  "File holding the Emacs major version that compiled the installed packages.")

(defun my/elpa-built-with ()
  "Major version recorded in `my/elpa-stamp', or nil."
  (ignore-errors
    (with-temp-buffer
      (insert-file-contents my/elpa-stamp)
      (string-trim (buffer-string)))))

(defun my/elpa-write-stamp ()
  (ignore-errors
    (with-temp-file my/elpa-stamp
      (insert (number-to-string emacs-major-version) "\n"))))

(when (and (file-directory-p package-user-dir)
           (not (equal (my/elpa-built-with) (number-to-string emacs-major-version))))
  (message "Emacs %d: recompiling packages built by another version (once)..."
           emacs-major-version)
  (let ((warning-minimum-level :error)
        (byte-compile-warnings nil))
    (ignore-errors (package-recompile-all)))
  (my/elpa-write-stamp))

;; --- Offline resilience ------------------------------------------------------
;; The laptop is expected to run with no connectivity. Two things break a
;; disconnected startup:
;;   1. `package-refresh-contents' hanging while a dead network times out.
;;   2. A `:ensure' for a not-yet-installed package erroring, which can abort
;;      the rest of init.el and drop you into a half-configured Emacs.
;; Probing once up front and gating both on the result avoids each.
;; Override manually with:  EMACS_OFFLINE=1 emacs
;; NOTE: the trailing `t' is load-bearing. `network-lookup-address-info' returns
;; a LIST OF IP ADDRESS VECTORS, not a boolean. `use-package-always-ensure'
;; treats any non-t, non-nil value as "the name of the package to install
;; instead", so leaking the address list here makes use-package try to install
;; a package called [137 184 119 0].
(defvar my/online-p
  (and (not (getenv "EMACS_OFFLINE"))
       (ignore-errors (network-lookup-address-info "melpa.org"))
       t)
  "Non-nil when the package archives looked reachable at startup.")

;; Only refresh the archive list when we have no cache AND we appear online
(when (and my/online-p (not package-archive-contents))
  (ignore-errors (package-refresh-contents)))

(unless (package-installed-p 'use-package)
  (when my/online-p
    (ignore-errors
      (package-refresh-contents)
      (package-install 'use-package))))

(require 'use-package)
;; Install missing packages only when online. Offline, use-package falls back to
;; whatever is already on disk and downgrades a miss to a warning, not an abort.
(setq use-package-always-ensure my/online-p)
(setq use-package-always-demand nil)
(setq use-package-verbose nil)

;; =============================================================================
;; FRAME & UI
;; =============================================================================

(menu-bar-mode -1)
(when (fboundp 'tool-bar-mode)    (tool-bar-mode -1))
(when (fboundp 'scroll-bar-mode)  (scroll-bar-mode -1))
(when (fboundp 'tooltip-mode)     (tooltip-mode -1))
(when (fboundp 'blink-cursor-mode)(blink-cursor-mode -1))

(column-number-mode t)
(line-number-mode t)
(size-indication-mode t)

(setq ring-bell-function 'ignore)

(when (fboundp 'fringe-mode) (fringe-mode '(4 . 0)))

(setq scroll-margin 4
      scroll-conservatively 101
      scroll-preserve-screen-position t
      auto-window-vscroll nil)

(setq frame-title-format
      '((:eval (if (buffer-file-name)
                   (abbreviate-file-name (buffer-file-name))
                 "%b"))
        " — Emacs"))

(add-to-list 'default-frame-alist '(fullscreen . maximized))

;; =============================================================================
;; FONT — FiraCode with ligatures
;;
;; Install once (both machines, needs internet / package manager):
;;   Ubuntu/Debian:  sudo apt install fonts-firacode
;;   Arch:           sudo pacman -S ttf-fira-code
;;   After install:  fc-cache -fv
;; =============================================================================

(defvar my/font-size 13
  "Point size for the default font. private.el may override this per machine.")

(defun my/set-font ()
  "Set FiraCode as primary font with fallbacks, at `my/font-size'."
  (when (display-graphic-p)
    (let ((family (cond
                   ((find-font (font-spec :name "FiraCode Nerd Font")) "FiraCode Nerd Font")
                   ((find-font (font-spec :name "Fira Code"))          "Fira Code")
                   ((find-font (font-spec :name "FiraCode"))           "FiraCode"))))
      (if family
          (set-frame-font (format "%s-%d" family my/font-size) nil t)
        (message "FiraCode not found — install fonts-firacode via your package manager.")))))

(my/set-font)
(add-hook 'server-after-make-frame-hook #'my/set-font)

;; Ligatures — installed once, works offline after that
(use-package ligature
  :config
  (ligature-set-ligatures
   'prog-mode
   '("www" "**" "***" "**/" "*>" "*/" "\\\\" "\\\\\\"
     "{-" "::" ":::" ":=" "!!" "!=" "!==" "-}"
     "--" "---" "-->" "->" "->>" "-<" "-<<" "-~"
     "#{" "#[" "##" "###" "####" "#(" "#?" "#_" "#_("
     ".-" ".=" ".." "..<" "..." "?=" "??" ";;"
     "/*" "/**" "/=" "/==" "/>" "//" "///" "&&"
     "||" "||=" "|=" "|>" "^=" "$>" "++" "+++"
     "+>" "=:=" "==" "===" "==>" "=>" "=>>" "<="
     "=<<" "=/=" ">-" ">=" ">=>" ">>" ">>-" ">>="
     ">>>" "<*" "<*>" "<|" "<|>" "<$" "<$>" "<!--"
     "<-" "<--" "<->" "<+" "<+>" "<=" "<==" "<=>"
     "<=<" "<>" "<<" "<<-" "<<=" "<<<" "<~" "<~~"
     "</" "</>" "~@" "~-" "~=" "~>" "~~" "~~>" "%%"
     ))
  (global-ligature-mode t))

;; =============================================================================
;; THEME — doom-dark+ (VS Code Da)
;; =============================================================================

(use-package doom-themes
  :config
  (setq doom-themes-enable-bold t
        doom-themes-enable-italic t)
  (load-theme 'doom-dark+ t)
  (doom-themes-org-config))

;; =============================================================================
;; MODELINE
;; =============================================================================

(setq-default mode-line-format
              '("%e"
                mode-line-front-space
                mode-line-mule-info
                mode-line-client
                mode-line-modified
                mode-line-remote
                "  "
                mode-line-buffer-identification
                "  "
                mode-line-position
                (vc-mode vc-mode)
                "  "
                mode-line-modes
                mode-line-misc-info
                mode-line-end-spaces))

;; =============================================================================
;; EDITING BEHAVIOR
;; =============================================================================

(set-language-environment "UTF-8")
(set-default-coding-systems 'utf-8)
(set-terminal-coding-system 'utf-8)
(set-keyboard-coding-system 'utf-8)
(prefer-coding-system 'utf-8)

(setq-default indent-tabs-mode nil)
(setq-default tab-width 4)
(setq-default fill-column 100)

(electric-pair-mode t)

(show-paren-mode t)
(setq show-paren-delay 0)
(setq show-paren-style 'mixed)

(delete-selection-mode t)

(global-auto-revert-mode t)
(setq auto-revert-verbose nil)

(add-hook 'prog-mode-hook #'display-line-numbers-mode)
(setq display-line-numbers-type 'relative)

(global-hl-line-mode t)

(add-hook 'before-save-hook #'delete-trailing-whitespace)
(setq require-final-newline t)

(setq-default word-wrap t)


;; Enable mouse/trackpad support in terminal Emacs
(unless (display-graphic-p)
  (xterm-mouse-mode t))

;; =============================================================================
;; FILE & BUFFER MANAGEMENT
;; =============================================================================

(setq backup-directory-alist `(("." . ,(expand-file-name "~/.emacs.d/backups/"))))
(setq backup-by-copying t
      delete-old-versions t
      kept-new-versions 6
      kept-old-versions 2
      version-control t)

(setq auto-save-file-name-transforms
      `((".*" ,(expand-file-name "~/.emacs.d/auto-saves/") t)))
(make-directory "~/.emacs.d/auto-saves/" t)
(make-directory "~/.emacs.d/backups/" t)

(setq create-lockfiles nil)

;; init.el is a symlink into the dotfiles repo; open it without the
;; "follow link to Git-controlled source file?" prompt.
(setq vc-follow-symlinks t)

(recentf-mode t)
(setq recentf-max-menu-items 30
      recentf-max-saved-items 100)

(save-place-mode t)
(savehist-mode t)

;; =============================================================================
;; COMPLETION — vertico + orderless + marginalia + consult
;; Installed once online, runs fully offline after that
;; =============================================================================

(use-package vertico
  :init (vertico-mode t)
  :config
  (setq vertico-count 15
        vertico-resize t))

(use-package orderless
  :config
  (setq completion-styles '(orderless basic)
        completion-category-defaults nil
        completion-category-overrides '((file (styles partial-completion)))))

(use-package marginalia
  :init (marginalia-mode t))

(use-package consult
  :bind
  (("C-x b"   . consult-buffer)
   ("C-x r b" . consult-bookmark)
   ("M-y"     . consult-yank-pop)
   ("M-s r"   . consult-ripgrep)
   ("M-s l"   . consult-line)
   ("M-s f"   . consult-find))
  :config
  (setq consult-preview-key 'any))

;; =============================================================================
;; CLIPBOARD — kill ring → system clipboard over SSH
;;
;; On a headless server there is no X clipboard (no xclip/xsel/DISPLAY).
;; Clipetty emits OSC 52 escape sequences, which travel up through SSH and tmux
;; to the terminal (Windows Terminal), which writes the local clipboard.
;;
;; Harmless in GUI frames — clipetty checks the frame and no-ops there.
;; =============================================================================

(use-package clipetty
  :hook (after-init . global-clipetty-mode))

;; =============================================================================
;; KEYBINDINGS
;; =============================================================================

;; -----------------------------------------------------------------------------
;; Ownership map — who gets which chord:
;;   C-h C-j C-k C-l   Emacs defaults (help, newline, kill-line, recenter)
;;   C-M-h j k l       tmux — pane movement
;;   M-o  h j k l      Emacs — window movement (windmove)
;;   C-c  ...          personal namespace
;; -----------------------------------------------------------------------------

(global-set-key (kbd "C-c m") #'execute-extended-command)

;; Window management
(global-set-key (kbd "C-c w h") #'split-window-horizontally)
(global-set-key (kbd "C-c w v") #'split-window-vertically)
(global-set-key (kbd "C-c w d") #'delete-window)
(global-set-key (kbd "C-c w o") #'delete-other-windows)
(global-set-key (kbd "C-c w b") #'balance-windows)

;; Window navigation — M-o prefix, then hjkl. M-o gets its own prefix map rather
;; than assuming the key is free: if Emacs or a package has put a command on M-o,
;; "M-o h" would otherwise fail with "starts with non-prefix key M-o" and stop init.el.
(define-prefix-command 'my/window-map)
(global-set-key (kbd "M-o") 'my/window-map)
(define-key my/window-map (kbd "h") #'windmove-left)
(define-key my/window-map (kbd "j") #'windmove-down)
(define-key my/window-map (kbd "k") #'windmove-up)
(define-key my/window-map (kbd "l") #'windmove-right)

;; Rehomed structural editing — tmux owns C-M-h and C-M-k at the terminal layer,
;; so mark-defun and kill-sexp never reach Emacs.
(global-set-key (kbd "C-c s h") #'mark-defun)
(global-set-key (kbd "C-c s k") #'kill-sexp)

(global-set-key (kbd "C-c k")   #'kill-current-buffer)
(global-set-key (kbd "C-c r")   #'recentf-open-files)
(global-set-key (kbd "C-c e")   #'eshell)

;; Move the current line up/down
(defun my/move-line-up ()
  "Transpose the current line with the one above it."
  (interactive)
  (transpose-lines 1)
  (forward-line -2))

(defun my/move-line-down ()
  "Transpose the current line with the one below it."
  (interactive)
  (forward-line 1)
  (transpose-lines 1)
  (forward-line -1))

(global-set-key (kbd "M-<up>")   #'my/move-line-up)
(global-set-key (kbd "M-<down>") #'my/move-line-down)

;; =============================================================================
;; TABS — project-level tabs with independent split layouts
;; =============================================================================
(tab-bar-mode 1)
(setq tab-bar-show 1)              ; hide bar when only one tab open
(setq tab-bar-close-button-show nil) ; no close buttons cluttering the bar
(setq tab-bar-new-button-show nil)   ; no + button
(setq tab-bar-tab-hints t)           ; show tab numbers

;; Tab navigation — fits existing C-c namespace
(global-set-key (kbd "C-c t n") #'tab-bar-new-tab)
(global-set-key (kbd "C-c t d") #'tab-bar-close-tab)
(global-set-key (kbd "C-c t r") #'tab-bar-rename-tab)
(global-set-key (kbd "C-c t o") #'tab-bar-switch-to-next-tab)
(global-set-key (kbd "C-c t p") #'tab-bar-switch-to-prev-tab)

;; Jump to tab by number — C-c t 1 .. C-c t 9
;; Deliberately NOT on M-1..M-5: those are digit-argument, and losing them
;; costs you M-3 C-n, M-5 C-k, and every other numeric-prefix idiom.
;; The closure over N here relies on the lexical-binding cookie at the top.
(dotimes (i 9)
  (let ((n (1+ i)))
    (global-set-key (kbd (format "C-c t %d" n))
                    (lambda () (interactive) (tab-bar-select-tab n)))))

;; =============================================================================
;; ORG MODE
;;
;; Same paths on every machine. What backs ~/org differs per machine (a network
;; mount on the server, a local synced folder on a laptop); see private.el.
;; =============================================================================

(global-set-key (kbd "C-c n") #'org-capture)
(global-set-key (kbd "C-c a") #'org-agenda)

(use-package org
  :ensure nil
  :hook (org-mode . visual-line-mode)
  :config
  (setq org-directory "~/org"
        org-default-notes-file "~/org/inbox.org"
        org-startup-indented t
        org-startup-folded t
        org-startup-with-inline-images t
        org-hide-emphasis-markers t
        org-pretty-entities t
        org-ellipsis " ▸"
        org-src-fontify-natively t
        org-src-tab-acts-natively t
        org-confirm-babel-evaluate nil
        org-return-follows-link t)

  ;; Quick note entry without hunting for the right file
  (setq org-capture-templates
        '(("n" "Quick note" entry
           (file+headline "~/org/inbox.org" "Inbox")
           "* %?\n  %U\n  %a"
           :empty-lines 1)
          ("t" "Task" entry
           (file+headline "~/org/tasks.org" "Tasks")
           "* TODO %?\n  SCHEDULED: %t\n  %U"
           :empty-lines 1)
          ("j" "Journal" entry
           (file+olp+datetree "~/org/journal.org")
           "* %?\n  %U"
           :empty-lines 1)))

  (setq org-agenda-files '("~/org/inbox.org"
                           "~/org/tasks.org")))

;; =============================================================================
;; PROGRAMMING
;; =============================================================================
(use-package treesit-auto
  :custom
  (treesit-auto-install 'prompt)
  :config
  (treesit-auto-add-to-auto-mode-alist 'all)
  (global-treesit-auto-mode))


(add-hook 'prog-mode-hook
          (lambda () (setq show-trailing-whitespace t)))


;; =============================================================================
;; PROFILE-SPECIFIC
;; =============================================================================

;; Servers: long-lived sessions and wide terminals
(when (my/profile-p "server")
  (setq recentf-max-saved-items 200)
  (setq-default fill-column 120))

;; =============================================================================
;; PRIVATE — host-specific settings from the private repo, when installed
;; =============================================================================

(load (expand-file-name "private.el" user-emacs-directory) t 'nomessage)

;; A fresh install compiled everything with this Emacs: record that.
(when (and (file-directory-p package-user-dir) (not (my/elpa-built-with)))
  (my/elpa-write-stamp))

;; =============================================================================
;; CUSTOM FILE
;; =============================================================================

(setq custom-safe-themes t)
(setq custom-file (expand-file-name "custom.el" user-emacs-directory))
(when (file-exists-p custom-file)
  (load custom-file nil 'nomessage))

;; =============================================================================
;; END OF INIT
;; =============================================================================
