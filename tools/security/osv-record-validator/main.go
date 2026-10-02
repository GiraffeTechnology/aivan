// osv-record-validator checks public OSV archives with the exact record decoder
// used by OSV-Scanner 2.6.0. It performs no network operations or semantic lint.
package main

import (
	"archive/zip"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	osvpb "github.com/ossf/osv-schema/bindings/go/osvschema"
	"google.golang.org/protobuf/encoding/protojson"
)

type archiveResult struct {
	Path    string `json:"path"`
	Records int    `json:"records"`
}

func validateArchive(path string) (archiveResult, error) {
	out := archiveResult{Path: path}
	archive, err := zip.OpenReader(path)
	if err != nil {
		return out, fmt.Errorf("%s: %w", path, err)
	}
	defer archive.Close()
	for _, member := range archive.File {
		if !strings.HasSuffix(member.Name, ".json") {
			continue
		}
		reader, err := member.Open()
		if err != nil {
			return out, fmt.Errorf("%s:%s: %w", path, member.Name, err)
		}
		content, readErr := io.ReadAll(reader)
		closeErr := reader.Close()
		if readErr != nil {
			return out, fmt.Errorf("%s:%s: %w", path, member.Name, readErr)
		}
		if closeErr != nil {
			return out, fmt.Errorf("%s:%s: %w", path, member.Name, closeErr)
		}
		// Keep the default decoder options identical to osvlocal/zip.go.
		if err := protojson.Unmarshal(content, &osvpb.Vulnerability{}); err != nil {
			return out, fmt.Errorf("%s:%s: %w", path, member.Name, err)
		}
		out.Records++
	}
	return out, nil
}

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "usage: osv-record-validator ARCHIVE.zip [ARCHIVE.zip ...]")
		os.Exit(2)
	}
	out := make(map[string]int)
	for _, path := range os.Args[1:] {
		archive, err := validateArchive(path)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		ecosystem := filepath.Base(filepath.Dir(path))
		if _, exists := out[ecosystem]; exists {
			fmt.Fprintln(os.Stderr, "duplicate ecosystem archive:", ecosystem)
			os.Exit(1)
		}
		out[ecosystem] = archive.Records
	}
	if err := json.NewEncoder(os.Stdout).Encode(out); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
}
