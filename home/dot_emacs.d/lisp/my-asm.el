;;; my-asm.el --- NASM editing, make and gdb helpers  -*- lexical-binding: t; -*-

;; Part of the core dotfiles (public repo): no hostnames or identifiers here.
;; Design notes live in the project doc GUIDE_Emacs_NASM_TRAMP.md.

(require 'use-package)
(require 'compile)
(require 'seq)

;; nasm-mode from MELPA. Skipped entirely when offline and not already installed,
;; so .asm files then stay in the built-in `asm-mode' instead of erroring.
(when (or (bound-and-true-p my/online-p) (locate-library "nasm-mode"))
  (use-package nasm-mode
    :ensure t
    :mode ("\\.asm\\'" "\\.nasm\\'" "\\.inc\\'")))

(defconst my/make-file-names '("Makefile" "makefile" "GNUmakefile")
  "File names that mark the root of a make project.")

(defun my/make-root (&optional dir)
  "Return the nearest directory at or above DIR that holds a makefile, or nil.
DIR defaults to `default-directory'.  Also works on remote (TRAMP) paths."
  (locate-dominating-file
   (or dir default-directory)
   (lambda (d)
     (seq-some (lambda (n) (file-exists-p (expand-file-name n d)))
               my/make-file-names))))

(defun my/compile-project ()
  "Run `compile' from the nearest makefile directory, else from here."
  (interactive)
  (let* ((root (my/make-root))
         (default-directory (or root default-directory)))
    (unless root
      (message "No makefile above %s; compiling here" default-directory))
    (call-interactively #'compile)))

(global-set-key (kbd "C-c c") #'my/compile-project)
(global-set-key (kbd "C-c g") #'gdb)

(provide 'my-asm)
;;; my-asm.el ends here
