/**
 * Renders the 10 backup codes once + a "Download as .txt" button.
 * The blob is built client-side; no server round-trip.
 */
import { Button } from "@/components/ui/button";

export function BackupCodesPanel({
  codes,
  onAcknowledge,
}: {
  codes: ReadonlyArray<string>;
  onAcknowledge: () => void;
}): React.JSX.Element {
  const handleDownload = (): void => {
    const lines = [
      "# VaultChain backup codes — keep these somewhere safe.",
      "# Each code can be used once if you lose access to your authenticator app.",
      "",
      ...codes,
      "",
    ];
    const blob = new Blob([lines.join("\n")], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "vaultchain-backup-codes.txt";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  return (
    <div className="flex flex-col gap-4" data-testid="backup-codes-panel">
      <p className="text-sm text-text-secondary">
        Save these one-time backup codes somewhere only you can read. Each works
        once if you lose access to your authenticator app.
      </p>
      <div className="grid grid-cols-2 gap-2 rounded-md bg-bg-surface-sunken p-3 font-mono text-sm">
        {codes.map((c) => (
          <code
            key={c}
            data-testid="backup-code-item"
            className="rounded bg-bg-surface px-2 py-1 text-text-primary"
          >
            {c}
          </code>
        ))}
      </div>
      <div className="flex flex-col gap-2 sm:flex-row">
        <Button
          variant="outline"
          type="button"
          data-testid="backup-download"
          onClick={handleDownload}
        >
          Download as .txt
        </Button>
        <Button
          type="button"
          data-testid="backup-saved"
          onClick={onAcknowledge}
        >
          I've saved them
        </Button>
      </div>
    </div>
  );
}
