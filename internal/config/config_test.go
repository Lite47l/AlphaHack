package config

import "testing"

func TestParseFeedsDefault(t *testing.T) {
	feeds, err := ParseFeeds(DefaultNewsFeeds)
	if err != nil || len(feeds) != 7 {
		t.Fatalf("feeds=%v err=%v", feeds, err)
	}
	if feeds[0].Name != "Банк России" || feeds[0].URL != "https://www.cbr.ru/rss/RssPress" {
		t.Errorf("first feed = %+v", feeds[0])
	}
}

func TestParseFeedsErrors(t *testing.T) {
	if f, err := ParseFeeds(" ; РБК | https://rbc.ru/rss ;"); err != nil || len(f) != 1 || f[0].Name != "РБК" {
		t.Fatalf("got %v, %v", f, err)
	}
	for _, bad := range []string{"no-url", "Имя|ftp://x", "|https://x", "Имя|"} {
		if _, err := ParseFeeds(bad); err == nil {
			t.Errorf("ParseFeeds(%q) must fail", bad)
		}
	}
}
