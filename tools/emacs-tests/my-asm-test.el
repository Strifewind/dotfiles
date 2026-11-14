;;; my-asm-test.el --- tests for my-asm  -*- lexical-binding: t; -*-
(require 'ert)
(require 'compile)
(require 'cl-lib)
(defvar my/online-p nil)
(require 'my-asm)

(defun my-asm-test--tree (&rest files)
  "Make a temp dir holding FILES (relative names); return its root with a trailing slash."
  (let ((root (file-name-as-directory (make-temp-file "my-asm-test" t))))
    (dolist (f files)
      (let ((path (expand-file-name f root)))
        (make-directory (file-name-directory path) t)
        (write-region "" nil path)))
    root))

(ert-deftest my-asm-test-root-found-in-parent ()
  (let ((root (my-asm-test--tree "Makefile" "src/a.asm")))
    (should (equal (my/make-root (expand-file-name "src/" root)) root))))

(ert-deftest my-asm-test-root-name-variants ()
  (dolist (name '("makefile" "GNUmakefile"))
    (let ((root (my-asm-test--tree name "src/a.asm")))
      (should (equal (my/make-root (expand-file-name "src/" root)) root)))))

(ert-deftest my-asm-test-root-none ()
  (let ((root (my-asm-test--tree "a.asm")))
    (should (null (my/make-root root)))))

(ert-deftest my-asm-test-compile-uses-root ()
  (let ((root (my-asm-test--tree "Makefile" "src/a.asm")) seen)
    (cl-letf (((symbol-function 'compile)
               (lambda (&rest _) (interactive) (setq seen default-directory))))
      (let ((default-directory (expand-file-name "src/" root)))
        (my/compile-project)))
    (should (equal seen root))))

(ert-deftest my-asm-test-compile-falls-back-here ()
  (let* ((root (my-asm-test--tree "src/a.asm"))
         (src (expand-file-name "src/" root))
         seen)
    (cl-letf (((symbol-function 'compile)
               (lambda (&rest _) (interactive) (setq seen default-directory))))
      (let ((default-directory src))
        (my/compile-project)))
    (should (equal seen src))))

(ert-deftest my-asm-test-nasm-error-clickable ()
  (with-temp-buffer
    (insert "prog.asm:12: error: parser: instruction expected\n")
    (compilation-mode)
    (font-lock-mode 1)
    (font-lock-ensure)
    (goto-char (point-min))
    (should (get-text-property (point) 'compilation-message))))

(ert-deftest my-asm-test-load-twice ()
  (load (locate-library "my-asm") nil t)
  (load (locate-library "my-asm") nil t)
  (should (eq (key-binding (kbd "C-c c")) 'my/compile-project))
  (should (eq (key-binding (kbd "C-c g")) 'gdb)))

;;; --- section-aware indentation in data sections (nasm-mode) ---
(ignore-errors (package-initialize))
(require 'nasm-mode nil t)

(defun my-asm-test--indent (text line)
  "Indentation of 1-based LINE of TEXT after indenting it in a NASM buffer."
  (with-temp-buffer
    (insert text)
    (nasm-mode)
    (goto-char (point-min))
    (forward-line (1- line))
    (indent-according-to-mode)
    (current-indentation)))

(defun my-asm-test--colon (text)
  "Type a colon at the end of TEXT in a NASM buffer; return (INDENT LINE)."
  (with-temp-buffer
    (insert text)
    (nasm-mode)
    (goto-char (point-max))
    (let ((last-command-event ?:))
      (call-interactively (key-binding ":")))
    (list (current-indentation)
          (buffer-substring (line-beginning-position) (line-end-position)))))

(ert-deftest my-asm-test-data-label-indented-in-data-sections ()
  (skip-unless (featurep 'nasm-mode))
  (dolist (sec '(".data" ".bss" ".rodata"))
    (should (= (my-asm-test--indent (format "section %s\nm: dd 0\n" sec) 2)
               nasm-basic-offset))))

(ert-deftest my-asm-test-data-colonless-stays-indented ()
  (skip-unless (featurep 'nasm-mode))
  (should (= (my-asm-test--indent "section .data\nmsg db 1\n" 2)
             nasm-basic-offset)))

(ert-deftest my-asm-test-text-label-goes-left ()
  (skip-unless (featurep 'nasm-mode))
  (should (= (my-asm-test--indent "section .text\n    main:\n" 2) 0)))

(ert-deftest my-asm-test-text-instruction-indented ()
  (skip-unless (featurep 'nasm-mode))
  (should (= (my-asm-test--indent "section .text\nmain:\nmov eax, 0\n" 3)
             nasm-basic-offset)))

(ert-deftest my-asm-test-section-directive-stays-left ()
  (skip-unless (featurep 'nasm-mode))
  (should (= (my-asm-test--indent "section .data\n    section .text\n" 2) 0)))

(ert-deftest my-asm-test-colon-in-data-keeps-indent ()
  (skip-unless (featurep 'nasm-mode))
  (should (equal (my-asm-test--colon "section .data\n    m")
                 (list 4 "    m:"))))

(ert-deftest my-asm-test-colon-in-text-goes-left ()
  (skip-unless (featurep 'nasm-mode))
  (should (= (car (my-asm-test--colon "section .text\n    main")) 0)))
