;;; my-tramp.el --- TRAMP settings for editing over SSH  -*- lexical-binding: t; -*-

;; Design: GUIDE_Emacs_NASM_TRAMP.md.  Nothing here touches the remote host.

(with-eval-after-load 'tramp
  ;; No .#lock files written into the remote directory.
  (setq remote-file-name-inhibit-locks t)
  ;; Do not run VC (git) over the SSH link for every remote file.
  ;; `vc-ignore-dir-regexp' is a string, so extend it once only.
  (unless (string-match-p (regexp-quote tramp-file-name-regexp)
                          vc-ignore-dir-regexp)
    (setq vc-ignore-dir-regexp
          (format "\\(%s\\)\\|\\(%s\\)"
                  vc-ignore-dir-regexp tramp-file-name-regexp))))

(provide 'my-tramp)
;;; my-tramp.el ends here
