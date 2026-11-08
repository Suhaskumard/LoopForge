package lib

import (
	"testing"
)

func TestPalindromeSimple(t *testing.T) {
	if !IsPalindrome("racecar") {
		t.Fatal("racecar is a palindrome")
	}
}

func TestPalindromeSentence(t *testing.T) {
	if !IsPalindrome("A man, a plan, a canal: Panama") {
		t.Fatal("sentence palindrome")
	}
}

func TestPalindromeNot(t *testing.T) {
	if IsPalindrome("hello") {
		t.Fatal("hello is not a palindrome")
	}
}

func TestPalindromeEmpty(t *testing.T) {
	if !IsPalindrome("") {
		t.Fatal("empty string is a palindrome")
	}
}

func TestPalindromeDigits(t *testing.T) {
	if !IsPalindrome("12321") || IsPalindrome("12345") {
		t.Fatal("digit handling")
	}
}
