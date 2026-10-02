package main

import (
	"archive/zip"
	"os"
	"path/filepath"
	"testing"
)

func TestExactRecordDecoder(t *testing.T) {
	cases := []struct {
		name, data string
		valid      bool
	}{
		{"valid", `{"id":"PUBLIC-CONTROL","modified":"2026-10-02T00:00:00Z"}`, true},
		{"no_semantic_lint", `{"id":"PUBLIC-CONTROL","severity":[{"type":"CVSS_V4","score":"CVSS:4.0/AV:N/"}],"affected":[{"ranges":[{"type":"GIT","repo":"https://example.com/public.git","events":[{"fixed":"abc.patch"}]}]}]}`, true},
		{"field_type", `{"id":7}`, false},
		{"affected_type", `{"affected":"malformed"}`, false},
		{"date", `{"modified":"not-a-date"}`, false},
		{"unknown_field", `{"unknown_control_field":true}`, false},
		{"duplicate_field", `{"id":"A","id":"B"}`, false},
	}
	for _, tt := range cases {
		t.Run(tt.name, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "control.zip")
			f, err := os.Create(path)
			if err != nil {
				t.Fatal(err)
			}
			z := zip.NewWriter(f)
			w, err := z.Create("PUBLIC-CONTROL.json")
			if err != nil {
				t.Fatal(err)
			}
			if _, err := w.Write([]byte(tt.data)); err != nil {
				t.Fatal(err)
			}
			if err := z.Close(); err != nil {
				t.Fatal(err)
			}
			if err := f.Close(); err != nil {
				t.Fatal(err)
			}
			out, err := validateArchive(path)
			if (err == nil) != tt.valid {
				t.Fatalf("valid=%v error=%v", tt.valid, err)
			}
			if tt.valid && out.Records != 1 {
				t.Fatalf("records=%d", out.Records)
			}
		})
	}
}
