// SPDX-License-Identifier: Apache-2.0
package app

import (
	"errors"
	"fmt"
	"sync"
	"testing"
	"time"

	"pgregory.net/rapid"
)

// TestProperty_P07_ShutdownOrdering is a property-based test verifying that
// the shutdown close-loop logic satisfies:
//   - Exact reverse construction order
//   - Exactly-once close per component
//   - Continues closing after errors
//   - Idempotence (second call returns same result)
//   - Bounded time
func TestProperty_P07_ShutdownOrdering(t *testing.T) {
	rapid.Check(t, func(rt *rapid.T) {
		n := rapid.IntRange(1, 10).Draw(rt, "numClosers")

		var order []int
		var mu sync.Mutex
		closers := make([]namedCloser, n)
		failFlags := make([]bool, n)

		for i := 0; i < n; i++ {
			idx := i
			shouldFail := rapid.Bool().Draw(rt, fmt.Sprintf("fail_%d", i))
			failFlags[i] = shouldFail
			closers[i] = namedCloser{
				name: fmt.Sprintf("c%d", i),
				fn: func() error {
					mu.Lock()
					order = append(order, idx)
					mu.Unlock()
					if shouldFail {
						return fmt.Errorf("close %d failed", idx)
					}
					return nil
				},
			}
		}

		// --- Execute the close loop (mirrors App.Close logic) ---
		executeClose := func() error {
			var closeErr error
			for i := len(closers) - 1; i >= 0; i-- {
				c := closers[i]
				if err := c.fn(); err != nil {
					closeErr = errors.Join(closeErr, fmt.Errorf("%s: %w", c.name, err))
				}
			}
			return closeErr
		}

		// First close — bounded time check
		start := time.Now()
		firstErr := executeClose()
		elapsed := time.Since(start)

		if elapsed > 5*time.Second {
			rt.Fatalf("Close took too long: %v", elapsed)
		}

		// Verify exact reverse order
		if len(order) != n {
			rt.Fatalf("expected %d closes, got %d", n, len(order))
		}
		for i := 0; i < len(order)-1; i++ {
			if order[i] <= order[i+1] {
				rt.Fatalf("not strictly decreasing (not reverse order): %v", order)
			}
		}

		// Verify exactly-once: each index appears exactly once
		seen := make(map[int]int)
		for _, idx := range order {
			seen[idx]++
		}
		for i := 0; i < n; i++ {
			if seen[i] != 1 {
				rt.Fatalf("component %d closed %d times, want 1", i, seen[i])
			}
		}

		// Verify errors don't stop other closers — all n were called
		// (already proven by len(order) == n above)

		// --- Idempotence via sync.Once ---
		// Simulate App.Close() with sync.Once wrapping
		var secondOrder []int
		closers2 := make([]namedCloser, n)
		for i := 0; i < n; i++ {
			idx := i
			shouldFail := failFlags[i]
			closers2[i] = namedCloser{
				name: fmt.Sprintf("c%d", i),
				fn: func() error {
					mu.Lock()
					secondOrder = append(secondOrder, idx)
					mu.Unlock()
					if shouldFail {
						return fmt.Errorf("close %d failed", idx)
					}
					return nil
				},
			}
		}

		var once sync.Once
		var onceErr error
		doClose := func() error {
			once.Do(func() {
				for i := len(closers2) - 1; i >= 0; i-- {
					c := closers2[i]
					if err := c.fn(); err != nil {
						onceErr = errors.Join(onceErr, fmt.Errorf("%s: %w", c.name, err))
					}
				}
			})
			return onceErr
		}

		err1 := doClose()
		err2 := doClose()

		// Second call returns same result
		if fmt.Sprint(err1) != fmt.Sprint(err2) {
			rt.Fatalf("idempotence violated: first=%v second=%v", err1, err2)
		}

		// Second call did not invoke closers again
		if len(secondOrder) != n {
			rt.Fatalf("idempotence: expected %d total calls, got %d", n, len(secondOrder))
		}

		// Verify error is nil only when no failures
		expectedFailCount := 0
		for _, f := range failFlags {
			if f {
				expectedFailCount++
			}
		}
		if expectedFailCount == 0 && firstErr != nil {
			rt.Fatalf("no failures configured but got error: %v", firstErr)
		}
		if expectedFailCount > 0 && firstErr == nil {
			rt.Fatalf("failures configured but got nil error")
		}
	})
}
