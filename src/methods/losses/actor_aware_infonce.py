
import torch
import torch.nn as nn
import torch.nn.functional as F


class ActorAwareInfoNCE(nn.Module):
    def __init__(self, temperature=0.07):
        super().__init__()
        self.temperature = temperature

    def forward(
        self,
        predicted_voice,
        target_voice,
        actor_ids,
    ):
        # predicted_voice: [B, 512]
        # target_voice: [B, 512]
        # actor_ids: list[str] of length B

        predicted_voice = F.normalize(
            predicted_voice, dim=-1
        )

        target_voice = F.normalize(
            target_voice, dim=-1
        )

        # Similarity matrix [B, B]
        logits = (
            predicted_voice @ target_voice.T
        ) / self.temperature

        batch_size = logits.size(0)

        # Same-actor mask
        same_actor = torch.tensor(
            [
                [a == b for b in actor_ids]
                for a in actor_ids
            ],
            device=logits.device,
            dtype=torch.bool,
        )

        # Preserve positive diagonal
        diagonal = torch.eye(
            batch_size,
            device=logits.device,
            dtype=torch.bool,
        )

        # Mask same-actor negatives only
        invalid_negatives = same_actor & ~diagonal

        logits = logits.masked_fill(
            invalid_negatives,
            float("-inf"),
        )

        targets = torch.arange(
            batch_size,
            device=logits.device,
        )

        return F.cross_entropy(logits, targets)
