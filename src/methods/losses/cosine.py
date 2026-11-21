import torch.nn as nn
import torch.nn.functional as F


class CosineRegressionLoss(nn.Module):
    def forward(self, predicted_voice, target_voice):
        cosine_similarity = F.cosine_similarity(
            predicted_voice,
            target_voice,
            dim=-1,
        )

        return (1 - cosine_similarity).mean()