"""
Sample PyTorch training script with drop-in privacy governance instrumentation
+ Differential Privacy training via Opacus PrivacyEngine
+ register_generate_fn for PrivacyRiskTests (canary + memorization)

Requirements:
  pip install torch opacus

Run:
  python train.py
"""

import os
import random
from typing import List, Tuple

# ✅ Minimal change: import + patch
import privacy_instrumentation.privacy_torch as privacy_torch

privacy_torch.patch_torch(
    domain="healthcare_summarization",
    intended_use="Summarize clinical notes for internal staff efficiency; not patient-facing.",
)

import torch
import torch.nn as nn
import torch.optim as optim

from torch.utils.data import Dataset, DataLoader

from opacus import PrivacyEngine


# ----------------------------
# Toy dataset
# ----------------------------

def build_toy_dataset() -> List[Tuple[str, int]]:
    # Label: 1 = "urgent", 0 = "non-urgent"
    # NOTE: These are synthetic strings — no real PII.
    return [
        ("patient has chest pain and shortness of breath", 1),
        ("severe headache with vision loss", 1),
        ("minor cough and sore throat", 0),
        ("routine medication refill request", 0),
        ("abdominal pain with fever and vomiting", 1),
        ("follow up appointment scheduling", 0),
        ("dizziness and fainting episode", 1),
        ("mild seasonal allergies", 0),
    ]


def build_vocab(texts: List[str]) -> dict:
    vocab = {"<PAD>": 0, "<UNK>": 1}
    for t in texts:
        for tok in t.lower().split():
            if tok not in vocab:
                vocab[tok] = len(vocab)
    return vocab


def encode(text: str, vocab: dict, max_len: int = 12) -> torch.Tensor:
    toks = text.lower().split()
    ids = [vocab.get(tok, vocab["<UNK>"]) for tok in toks][:max_len]
    ids += [vocab["<PAD>"]] * (max_len - len(ids))
    return torch.tensor(ids, dtype=torch.long)


class ToyTextDataset(Dataset):
    def __init__(self, data: List[Tuple[str, int]], vocab: dict, max_len: int = 12):
        self.data = data
        self.vocab = vocab
        self.max_len = max_len

    def __len__(self):
        return len(self.data)

    def __getitem__(self, idx: int):
        text, label = self.data[idx]
        x = encode(text, self.vocab, self.max_len)
        y = torch.tensor(label, dtype=torch.long)
        return x, y


# ----------------------------
# Toy model
# ----------------------------

class ToyTextClassifier(nn.Module):
    def __init__(self, vocab_size: int, embed_dim: int = 32, hidden_dim: int = 64):
        super().__init__()
        self.emb = nn.Embedding(vocab_size, embed_dim)
        self.fc1 = nn.Linear(embed_dim, hidden_dim)
        self.act = nn.ReLU()
        self.fc2 = nn.Linear(hidden_dim, 2)

    def forward(self, input_ids: torch.Tensor) -> torch.Tensor:
        # input_ids: [B, T]
        x = self.emb(input_ids)            # [B, T, D]
        x = x.mean(dim=1)                  # [B, D]
        x = self.fc1(x)                    # [B, H]
        x = self.act(x)                    # [B, H]
        logits = self.fc2(x)               # [B, 2]
        return logits


# ----------------------------
# Train loop (DP)
# ----------------------------

def train():
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    data = build_toy_dataset()
    random.shuffle(data)

    texts = [t for t, _ in data]
    vocab = build_vocab(texts)

    dataset = ToyTextDataset(data, vocab=vocab, max_len=12)

    # IMPORTANT FOR OPACUS:
    # Opacus expects true shuffling + known batch size.
    batch_size = 4
    train_loader = DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=True,
        drop_last=True,  # good practice for DP training
    )

    model = ToyTextClassifier(vocab_size=len(vocab)).to(device)
    criterion = nn.CrossEntropyLoss()

    optimizer = optim.AdamW(model.parameters(), lr=3e-3)

    # ✅ Enable DP with Opacus
    noise_multiplier = 1.1
    max_grad_norm = 1.0

    privacy_engine = PrivacyEngine()

    model, optimizer, train_loader = privacy_engine.make_private(
        module=model,
        optimizer=optimizer,
        data_loader=train_loader,
        noise_multiplier=noise_multiplier,
        max_grad_norm=max_grad_norm,
    )

    # ---------------------------------------------------------
    # ✅ Generate function for privacy risk tests (canary/mem)
    # ---------------------------------------------------------
    def generate_fn(prompt: str) -> str:
        """
        This project isn't a generative model — it's a classifier.
        So this "generate" function returns a deterministic text report of:
          - predicted class
          - probabilities
        which is still useful for leakage/memorization smoke tests.
        """
        model.eval()
        with torch.no_grad():
            x = encode(prompt, vocab).unsqueeze(0).to(device)  # [1, T]
            logits = model(x)
            probs = torch.softmax(logits, dim=-1).cpu().tolist()[0]
            pred = int(torch.argmax(logits, dim=-1).cpu().item())

        label_str = "urgent" if pred == 1 else "non-urgent"
        return (
            f"prediction={label_str} "
            f"p_non_urgent={probs[0]:.4f} "
            f"p_urgent={probs[1]:.4f}"
        )

    # ✅ Register with privacy instrumentation so _flush_bundle can run tests at exit
    privacy_torch.register_generate_fn(generate_fn)

    # ---- Training loop ----
    model.train()
    epochs = 5

    for epoch in range(epochs):
        total_loss = 0.0
        total_correct = 0
        total_count = 0

        for batch_x, batch_y in train_loader:
            batch_x = batch_x.to(device)
            batch_y = batch_y.to(device)

            optimizer.zero_grad()
            logits = model(batch_x)
            loss = criterion(logits, batch_y)
            loss.backward()
            optimizer.step()

            total_loss += float(loss.item()) * batch_x.size(0)
            preds = logits.argmax(dim=-1)
            total_correct += int((preds == batch_y).sum().item())
            total_count += int(batch_x.size(0))

        avg_loss = total_loss / max(total_count, 1)
        acc = total_correct / max(total_count, 1)

        # Optional: report epsilon spent so far
        try:
            epsilon = privacy_engine.get_epsilon(delta=1e-5)
            print(f"epoch={epoch+1}/{epochs} loss={avg_loss:.4f} acc={acc:.3f} epsilon={epsilon:.2f}")
        except Exception:
            print(f"epoch={epoch+1}/{epochs} loss={avg_loss:.4f} acc={acc:.3f}")

    # ✅ Save checkpoint (privacy_torch patches torch.save and logs checksum/permissions)
    os.makedirs("./checkpoints", exist_ok=True)
    ckpt_path = "./checkpoints/toy_classifier_dp.pt"

    torch.save(
        {
            "model_state_dict": model.state_dict(),
            "vocab": vocab,
            "dp": {
                "noise_multiplier": noise_multiplier,
                "max_grad_norm": max_grad_norm,
            },
        },
        ckpt_path,
    )
    
    # PRIVACY FIX: Restrict checkpoint file permissions to owner-only (0o600).
    # Healthcare models trained on clinical notes require strict access controls.
    # GDPR Art. 5(1)(f) - integrity and confidentiality principle.
    # GDPR Art. 32 - security of processing requires appropriate technical measures.
    # HIPAA: Also aligns with technical safeguards for PHI-derived artifacts.
    os.chmod(ckpt_path, 0o600)
    print(f"Saved checkpoint: {ckpt_path}")

    # Quick inference using generate_fn
    test_text = "patient reports severe chest pain"
    print(f"Test: '{test_text}' -> {generate_fn(test_text)}")


if __name__ == "__main__":
    train()
    print("\nDone. Governance bundle should be written under ./governance_out/<run_id>/")
    print(" - governance_context_bundle.json")
    print(" - events.jsonl  (includes torch.save + dp_enabled_detected + canary/mem tests if enabled)")
