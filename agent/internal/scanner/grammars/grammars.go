// SPDX-License-Identifier: Apache-2.0
package grammars

import (
	"crypto/sha256"
	"embed"
	"encoding/hex"
	"encoding/json"
	"fmt"
)

//go:embed *.wasm
var WasmFiles embed.FS

//go:embed grammars.lock.json
var LockJSON []byte

type GrammarMeta struct {
	Name      string `json:"name"`
	Version   string `json:"version"`
	SHA256    string `json:"sha256"`
	Licence   string `json:"licence"`
	SourceURL string `json:"source_url"`
	PURL      string `json:"purl"`
}

type LockFile struct {
	Version  string                 `json:"version"`
	Grammars map[string]GrammarMeta `json:"grammars"`
}

// VerifyGrammar checks one grammar blob against its locked SHA-256 digest.
//
// Extracted from `LoadGrammars` so the verification can be exercised with a TAMPERED blob.
// The embedded `.wasm` files cannot be modified at runtime -- that is the point of `go:embed` --
// so while this check lived inline there was no way for any test to observe it rejecting
// anything, and therefore no way to tell a working check from a deleted one. Q-25's negative
// control in design Appendix B is "skip digest verification when the blob loads successfully",
// which presupposes exactly this seam.
//
// Behaviour is unchanged: same comparison, same error text, same call site.
func VerifyGrammar(filename string, data []byte, meta GrammarMeta) error {
	hash := sha256.Sum256(data)
	digest := hex.EncodeToString(hash[:])
	if digest != meta.SHA256 {
		return fmt.Errorf("SHA-256 mismatch for %s: expected %s, got %s", filename, meta.SHA256, digest)
	}
	return nil
}

// LoadGrammars parses grammars.lock.json and verifies every embedded .wasm file against its SHA-256 digest.
func LoadGrammars() (map[string][]byte, LockFile, error) {
	var lock LockFile
	if err := json.Unmarshal(LockJSON, &lock); err != nil {
		return nil, lock, fmt.Errorf("unmarshal grammars.lock.json: %w", err)
	}

	result := make(map[string][]byte)
	for name, meta := range lock.Grammars {
		filename := fmt.Sprintf("%s.wasm", name)
		data, err := WasmFiles.ReadFile(filename)
		if err != nil {
			return nil, lock, fmt.Errorf("read embedded grammar %s: %w", filename, err)
		}

		if err := VerifyGrammar(filename, data, meta); err != nil {
			return nil, lock, err
		}

		result[name] = data
	}

	return result, lock, nil
}
