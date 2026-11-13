;;; my-tramp-test.el --- tests for my-tramp  -*- lexical-binding: t; -*-
(require 'ert)
(require 'tramp)
(require 'my-tramp)

(ert-deftest my-tramp-test-vc-skips-remote ()
  (should (string-match-p vc-ignore-dir-regexp "/ssh:host:/home/u/")))

(ert-deftest my-tramp-test-locks-inhibited ()
  (should (eq remote-file-name-inhibit-locks t)))

(ert-deftest my-tramp-test-load-twice ()
  (let ((before vc-ignore-dir-regexp))
    (load (locate-library "my-tramp") nil t)
    (should (equal before vc-ignore-dir-regexp))))
