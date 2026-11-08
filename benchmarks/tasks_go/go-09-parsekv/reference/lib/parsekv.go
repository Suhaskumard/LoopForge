package lib

import (
	"errors"
	"strings"
)

func ParseKV(s string) (map[string]string, error) {
	out := map[string]string{}
	if strings.TrimSpace(s) == "" {
		return out, nil
	}
	for _, item := range strings.Split(s, ";") {
		item = strings.TrimSpace(item)
		if item == "" {
			continue
		}
		parts := strings.SplitN(item, "=", 2)
		if len(parts) != 2 {
			return nil, errors.New("missing '=' in item")
		}
		key := strings.TrimSpace(parts[0])
		if key == "" {
			return nil, errors.New("empty key")
		}
		out[key] = strings.TrimSpace(parts[1])
	}
	return out, nil
}
