"""
CNN architecture for the existing trained weights.

PROVENANCE UPDATE: this class now matches the reference `CNN2D` /
`predict_user_input` implementation the project owner confirmed as the actual
prediction logic for this model. It replaces an earlier best-effort
reconstruction (documented in git history) that used a different -- also
shape-compatible, but not spatially equivalent -- reshape/pooling scheme
(17x1 with asymmetric pooling). A `state_dict`'s tensor shapes alone cannot
distinguish between the two, since both happen to produce a flattened size of
256; only the confirmed reference implementation tells us which one the
weights were actually trained under. The stored weights are unchanged either
way -- only the input reshape and pooling symmetry were corrected here to
match the confirmed reference:

    conv.0.weight  (32, 1, 3, 3)   -> Conv2d(1, 32, kernel_size=3, padding=1)
    conv.1.*                        -> BatchNorm2d(32)
    conv.4.weight  (64, 32, 3, 3)  -> Conv2d(32, 64, kernel_size=3, padding=1)
    conv.5.*                        -> BatchNorm2d(64)
    fc.1.weight    (64, 256)       -> Linear(256, 64)
    fc.4.weight    (2, 64)         -> Linear(64, 2)

The input to this model is a (batch, 1, 8, 8) tensor: the 17 scaled features,
edge-padded to 64 values and reshaped into an 8x8 grid. That padding/reshape
happens in predictor.py (mirroring the confirmed `predict_user_input`
reference exactly) -- this module only defines the network itself.
"""
import torch
from torch import nn

N_CLASSES = 2


class ExoplanetCNN(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(1, 32, kernel_size=3, padding=1),   # conv.0
            nn.BatchNorm2d(32),                            # conv.1
            nn.ReLU(),                                     # conv.2 (no params)
            nn.MaxPool2d(2, 2),                             # conv.3 (no params)
            nn.Conv2d(32, 64, kernel_size=3, padding=1),   # conv.4
            nn.BatchNorm2d(64),                            # conv.5
            nn.ReLU(),                                     # conv.6 (no params)
            nn.MaxPool2d(2, 2),                             # conv.7 (no params)
        )
        self.fc = nn.Sequential(
            nn.Flatten(),
            nn.Linear(64 * 2 * 2, 64),  # fc.1
            nn.ReLU(),                   # fc.2 (no params)
            nn.Dropout(0.35),            # fc.3 (no params; inert in eval())
            nn.Linear(64, N_CLASSES),    # fc.4
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x is already (batch, 1, 8, 8) -- reshaping happens in predictor.py.
        return self.fc(self.conv(x))


def load_cnn(state_dict: "OrderedDict") -> ExoplanetCNN:  # noqa: F821
    model = ExoplanetCNN()
    model.load_state_dict(state_dict)
    model.eval()
    return model
