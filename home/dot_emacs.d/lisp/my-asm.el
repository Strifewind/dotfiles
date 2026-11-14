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

;; --- Data sections: keep variables indented ---------------------------------
;; nasm-mode treats any `name:' as a label and forces it to column 0.  The
;; course template indents variables in .data/.bss/.rodata, so inside those
;; sections every line is indented one level instead.  Elsewhere nasm-mode
;; behaves as usual.

(defvar nasm-basic-offset)

(defconst my/nasm-data-sections '(".data" ".bss" ".rodata")
  "Section names whose lines are indented one level.")

(defun my/nasm-in-data-section-p ()
  "Non-nil when the line at point sits inside a data-like section."
  (save-excursion
    (beginning-of-line)
    (and (re-search-backward
          "^[ \t]*\\(?:section\\|segment\\)[ \t]+\\(\\.[[:alnum:]_]+\\)" nil t)
         (member (match-string-no-properties 1) my/nasm-data-sections)
         t)))

(defun my/nasm-data-line-p ()
  "Non-nil when the current line is an ordinary line in a data section."
  (and (my/nasm-in-data-section-p)
       (save-excursion
         (beginning-of-line)
         (not (looking-at
               "[ \t]*\\(?:$\\|\\(?:section\\|segment\\|global\\|extern\\)\\_>\\|%\\)")))))

(defun my/nasm-indent-line-in-data (orig &rest args)
  "Around advice for `nasm-indent-line': indent data-section lines one level."
  (if (my/nasm-data-line-p)
      (let ((from-end (- (line-end-position) (point))))
        (indent-line-to nasm-basic-offset)
        (goto-char (max (point) (- (line-end-position) from-end))))
    (apply orig args)))

(defun my/nasm-colon-in-data (orig &rest args)
  "Around advice for `nasm-colon': a plain colon inside data sections."
  (if (my/nasm-in-data-section-p)
      (self-insert-command (prefix-numeric-value current-prefix-arg))
    (apply orig args)))

(with-eval-after-load 'nasm-mode
  ;; Instructions and variables share one 4-column step, as in the template.
  (setq-default nasm-basic-offset 4)
  (advice-add 'nasm-indent-line :around #'my/nasm-indent-line-in-data)
  (advice-add 'nasm-colon :around #'my/nasm-colon-in-data))

(provide 'my-asm)
;;; my-asm.el ends here
