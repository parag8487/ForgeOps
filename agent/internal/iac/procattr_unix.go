// SPDX-License-Identifier: Apache-2.0
//go:build !windows

package iac

import (
	"os/exec"
	"syscall"
	"time"
)

// setProcessGroup creates a new process group for the child so we can
// signal tofu AND every provider plugin it spawned.
func setProcessGroup(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
}

// terminateGroup sends SIGTERM to the entire process group, waits for
// the grace period, then sends SIGKILL if still alive.
func terminateGroup(cmd *exec.Cmd, grace time.Duration) {
	if cmd.Process == nil {
		return
	}
	pgid := -cmd.Process.Pid // negative pid targets the whole group
	_ = syscall.Kill(pgid, syscall.SIGTERM)
	done := make(chan struct{})
	go func() {
		cmd.Wait()
		close(done)
	}()
	select {
	case <-done:
		return
	case <-time.After(grace):
		_ = syscall.Kill(pgid, syscall.SIGKILL)
	}
}
