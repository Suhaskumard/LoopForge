import { describe, expect, it } from "vitest";
import { encodeQr, formatBits, pickVersion, versionBits } from "../lib/qr";
import reference from "./fixtures/qr_reference.json";

// Reference matrices were generated with the python `qrcode` library (ECC M, byte mode):
// one per mask pattern, plus the library's own automatic mask choice.
const rows = (m: boolean[][]) => m.map((r) => r.map((v) => (v ? "1" : "0")).join(""));

describe("QR encoder", () => {
  it("BCH codes match the published values", () => {
    expect(formatBits(0)).toBe(0b101010000010010); // level M, mask 0
    expect(versionBits(7)).toBe(0x07c94);
    expect(versionBits(10)).toBe(0x0a4d3);
  });

  for (const sample of reference.samples) {
    const label = `${sample.text.slice(0, 24)}… (v${sample.version})`;

    it(`picks the same version as the reference: ${label}`, () => {
      expect(pickVersion(new TextEncoder().encode(sample.text).length)).toBe(sample.version);
    });

    it(`matches the reference bit for bit for every mask: ${label}`, () => {
      for (const [mask, expected] of Object.entries(sample.masks)) {
        expect(rows(encodeQr(sample.text, Number(mask)).modules), `mask ${mask}`).toEqual(expected);
      }
    });

    it(`chooses the same mask automatically: ${label}`, () => {
      expect(rows(encodeQr(sample.text).modules)).toEqual(sample.auto);
    });
  }
});
