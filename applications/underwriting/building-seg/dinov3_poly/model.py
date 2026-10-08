"""
The stage-2 network: one encoder-decoder, four heads.

A COMPACT CONV NET, NOT A ViT. The crop is the point of this design -- a p10
building is magnified 4.7x into 128 output cells, where the tile-level decoder
gave it 13. Feeding that crop to a patch-16 transformer would throw the gain
straight back: 256/16 = 16 tokens across, coarser than the tile head it
replaces. Corner placement needs stride, and convolutions are where stride is
cheap.

Output is at stride 2 (128 for a 256 crop). Stride 1 doubles cost for cells
already 0.43-1.45 scene px wide, and the offset head covers the remainder.
"""
import torch
import torch.nn as nn
import torch.nn.functional as F


def gn(c):
    """GroupNorm with a divisor that actually divides c. Batches here are big
    but crops are small, and BatchNorm on 4-channel inputs with heavy crop
    jitter was noisier in the same role in dinov3_v2."""
    for g in (32, 16, 8, 4, 2, 1):
        if c % g == 0:
            return nn.GroupNorm(g, c)
    return nn.GroupNorm(1, c)


class Block(nn.Module):
    def __init__(self, cin, cout, stride=1):
        super().__init__()
        self.c1 = nn.Conv2d(cin, cout, 3, stride, 1, bias=False)
        self.n1 = gn(cout)
        self.c2 = nn.Conv2d(cout, cout, 3, 1, 1, bias=False)
        self.n2 = gn(cout)
        self.skip = (nn.Identity() if cin == cout and stride == 1
                     else nn.Sequential(nn.Conv2d(cin, cout, 1, stride, bias=False),
                                        gn(cout)))

    def forward(self, x):
        y = F.relu(self.n1(self.c1(x)), True)
        y = self.n2(self.c2(y))
        return F.relu(y + self.skip(x), True)


class SimpleEncoder(nn.Module):
    """Strides 2/4/8/16/32, no downloads, ~4M params."""
    chans = (32, 64, 128, 256, 256)

    def __init__(self, cin=4, width=1.0):
        super().__init__()
        c = [max(8, int(x * width)) for x in self.chans]
        self.chans = tuple(c)
        self.s2 = nn.Sequential(nn.Conv2d(cin, c[0], 3, 2, 1, bias=False),
                                gn(c[0]), nn.ReLU(True), Block(c[0], c[0]))
        self.s4 = Block(c[0], c[1], 2)
        self.s8 = Block(c[1], c[2], 2)
        self.s16 = Block(c[2], c[3], 2)
        self.s32 = Block(c[3], c[4], 2)

    def forward(self, x):
        f2 = self.s2(x)
        f4 = self.s4(f2)
        f8 = self.s8(f4)
        f16 = self.s16(f8)
        return [f2, f4, f8, f16, self.s32(f16)]


class ResNetEncoder(nn.Module):
    """
    torchvision resnet18, stem widened to `cin` channels.

    THE EXTRA INPUT CHANNEL IS ZERO-INITIALISED IN THE WEIGHT, which is safe
    here and is not the trap it would be on an output projection: the gradient
    w.r.t. a zero WEIGHT is (input x grad_out), which is non-zero, so the box
    channel starts neutral and still learns. Zeroing a weight only kills
    learning when it also zeroes the gradient reaching the layer's INPUT.
    """

    def __init__(self, cin=4, pretrained=True):
        super().__init__()
        from torchvision.models import resnet18
        try:
            net = resnet18(weights="IMAGENET1K_V1" if pretrained else None)
        except Exception as e:                       # offline / old torchvision
            print(f"[model] pretrained resnet18 unavailable ({e}); random init")
            net = resnet18(weights=None)
        w = net.conv1.weight.data
        conv = nn.Conv2d(cin, 64, 7, 2, 3, bias=False)
        conv.weight.data.zero_()
        conv.weight.data[:, :min(cin, 3)] = w[:, :min(cin, 3)]
        net.conv1 = conv
        self.stem = nn.Sequential(net.conv1, net.bn1, net.relu)   # s2
        self.pool = net.maxpool                                   # s4
        self.l1, self.l2, self.l3, self.l4 = (net.layer1, net.layer2,
                                              net.layer3, net.layer4)
        self.chans = (64, 64, 128, 256, 512)

    def forward(self, x):
        f2 = self.stem(x)
        f4 = self.l1(self.pool(f2))
        f8 = self.l2(f4)
        f16 = self.l3(f8)
        return [f2, f4, f8, f16, self.l4(f16)]


class Decoder(nn.Module):
    """Top-down with lateral 1x1s, terminating at stride 2."""

    def __init__(self, chans, dim=128):
        super().__init__()
        self.lat = nn.ModuleList(nn.Conv2d(c, dim, 1) for c in chans)
        self.smooth = nn.ModuleList(Block(dim, dim) for _ in chans[:-1])

    def forward(self, feats):
        x = self.lat[-1](feats[-1])
        for i in range(len(feats) - 2, -1, -1):
            x = F.interpolate(x, size=feats[i].shape[-2:], mode="bilinear",
                              align_corners=False)
            x = self.smooth[i](x + self.lat[i](feats[i]))
        return x                                    # stride 2


class PolyNet(nn.Module):
    """
    (B, 4, S, S) -> dict of logits at (B, ., S//2, S//2)

    Channel 3 of the input is the box rectangle, not a segmentation mask. See
    README: feeding stage 1's mask back would reintroduce the mask dependence
    this project exists to remove, while the box survives a locally wrong
    boundary and still says which building is the subject.
    """

    def __init__(self, cin=4, dim=128, encoder="resnet18", pretrained=True,
                 edge=True, width=1.0):
        super().__init__()
        self.enc = (ResNetEncoder(cin, pretrained) if encoder == "resnet18"
                    else SimpleEncoder(cin, width))
        self.dec = Decoder(self.enc.chans, dim)
        self.use_edge = edge

        def head(cout):
            return nn.Sequential(nn.Conv2d(dim, dim, 3, 1, 1), gn(dim),
                                 nn.ReLU(True), nn.Conv2d(dim, cout, 1))

        self.h_mask = head(1)
        self.h_vmap = head(1)
        self.h_voff = head(2)
        self.h_edge = head(1) if edge else None

        # Corners cover ~0.3% of the map. Without a negative prior the first
        # epochs are spent pushing every logit down and the offset branch
        # trains through a dead heatmap. This IS a plain conv bias, so unlike a
        # dot-product head it survives contact with the features.
        nn.init.constant_(self.h_vmap[-1].bias, -4.0)
        if edge:
            nn.init.constant_(self.h_edge[-1].bias, -2.0)

    def forward(self, x):
        f = self.dec(self.enc(x))
        out = {"mask": self.h_mask(f), "vmap": self.h_vmap(f),
               "voff": self.h_voff(f)}
        if self.h_edge is not None:
            out["edge"] = self.h_edge(f)
        return out


def build(**kw):
    m = PolyNet(**kw)
    n = sum(p.numel() for p in m.parameters()) / 1e6
    print(f"[model] PolyNet {kw.get('encoder','resnet18')} "
          f"dim={kw.get('dim',128)} edge={kw.get('edge',True)}  {n:.2f}M params")
    return m
