"""
Losses. BCE+Dice everywhere dense, masked L1 on the offsets.

WHY DICE ON THE VERTEX MAP AND NOT CORNERNET FOCAL. Penalty-reduced focal
weights the negative term by (1 - t)^beta, which by construction FORGIVES
activation near a true peak -- exactly where duplicate corners appear. Dice
scores the predicted blob set against the target blob set as a whole, so an
extra peak costs overlap and cannot be discounted for being close to a real
one. SAMPolyBuild uses BCEDice here, and a vertex head trained with focal
measured 12.9% corner precision while emitting 2.06 vertices per GT vertex.

BCE alone would be swamped: corners occupy roughly 3x3 cells each out of
128x128, well under 1%. The sum is what works -- BCE gives per-pixel gradient
everywhere, Dice supplies the set-level penalty BCE cannot express.
"""
import torch
import torch.nn as nn
import torch.nn.functional as F


class BCEDice(nn.Module):
    """
    BCE-with-logits + soft Dice on the sigmoid.

    pos_weight scales the positive BCE term; SAMPolyBuild uses 2 for the mask
    and edge heads, where the positive class is a minority, and 1 for the
    vertex map, where Dice already carries the imbalance.
    """

    def __init__(self, pos_weight=1.0, dice_weight=1.0, eps=1.0):
        super().__init__()
        self.pos_weight = float(pos_weight)
        self.dice_weight = float(dice_weight)
        self.eps = eps

    def forward(self, logit, target):
        pw = torch.as_tensor(self.pos_weight, device=logit.device,
                             dtype=logit.dtype)
        bce = F.binary_cross_entropy_with_logits(logit, target, pos_weight=pw)
        p = torch.sigmoid(logit)
        dims = tuple(range(1, p.dim()))
        num = 2.0 * (p * target).sum(dims) + self.eps
        den = p.sum(dims) + target.sum(dims) + self.eps
        return bce + self.dice_weight * (1.0 - (num / den)).mean()


def masked_offset_loss(logit, target, mask):
    """
    L1 on sigmoid(logit) at cells that have a target, averaged per channel.

    THE OFFSET HEAD IS SIGMOID, NOT TANH, because render_vertex stores the
    remainder after a FLOOR -- the target lives in [0, 1), not [-0.5, 0.5].
    Pairing tanh with a floor-based target, or sigmoid with a round-based one,
    biases every corner by half a cell in a fixed direction, which no shape
    check would catch.

    Cells with no corner are excluded rather than regressed to zero: zero is a
    legitimate offset value (a corner exactly on a cell boundary), so training
    empty cells toward it would fight the real targets.
    """
    p = torch.sigmoid(logit)
    n = mask.sum().clamp(min=1.0)
    return (torch.abs(p - target) * mask).sum() / n / p.shape[1]


class PolyLoss(nn.Module):
    """The four heads, weighted. Returns (total, dict of parts for logging)."""

    def __init__(self, w_mask=1.0, w_vmap=1.0, w_voff=1.0, w_edge=1.0):
        super().__init__()
        self.mask = BCEDice(pos_weight=2.0)
        self.vmap = BCEDice(pos_weight=1.0)
        self.edge = BCEDice(pos_weight=2.0)
        self.w = dict(mask=w_mask, vmap=w_vmap, voff=w_voff, edge=w_edge)

    def forward(self, out, tgt):
        parts = {
            "mask": self.mask(out["mask"], tgt["mask"]),
            "vmap": self.vmap(out["vmap"], tgt["vmap"]),
            "voff": masked_offset_loss(out["voff"], tgt["voff"], tgt["vmask"]),
        }
        if "edge" in out and "edge" in tgt:
            parts["edge"] = self.edge(out["edge"], tgt["edge"])
        total = sum(self.w[k] * v for k, v in parts.items())
        return total, {k: float(v) for k, v in parts.items()}
