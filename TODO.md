# Before the first push — dotfiles (core)

The baseline from the Phase 0 inventory (2026-10-02) is in: init.el, tmux.conf,
.profile, the prompt palettes and the merged aliases. Before pushing to GitHub:

- [ ] Read `home/dot_bashrc.d/50-aliases.sh` once. It is the union of every
      machine's aliases, so some are new to each one (`rm -I`, `cp -i`, `mv -i`, `du1`).
- [ ] `.githooks/leakcheck --all`
- [ ] The rehearsal loop (guide, Phase 1 step 6) for all three profiles.
- [ ] Delete this file, commit, push.
