import torch.nn as nn
import torch.nn.functional as F

class VoiceMLP(nn.Module):
    def __init__(self, input_dim = 768, hidden_dim = 1024, output_dim = 512):
        super().__init__()
        self.network = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.GELU(),
            nn.Linear(hidden_dim, output_dim),
        )

    def forward(self, image_embedding):
        voice_embedding = self.network(image_embedding)

        return F.normalize(voice_embedding, dim=-1)
