"""Density-model interface and a CSRNet implementation.

The rest of the pipeline only depends on the ``DensityModel`` protocol:

    predict(tile_rgb: PIL.Image) -> np.ndarray  # HxW density, sums to ~count

Two concrete models are provided:

* ``CSRNet``        - the real, standard dilated-CNN crowd counter. Output is at
                      1/8 input resolution and its sum is the head count. Load
                      trained weights with ``load_csrnet(weights_path)``.
* ``FallbackModel`` - a texture-heuristic estimator (in ``fallback.py``) that
                      needs no weights, so the whole pipeline runs today. It is
                      NOT accurate; it exists to prove the plumbing and to give a
                      heatmap shape until a trained model is dropped in.

``load_model()`` returns CSRNet if torch + weights are available, otherwise the
fallback (with a clear warning).
"""

from __future__ import annotations

import sys
from typing import Optional, Protocol

import numpy as np
from PIL import Image

IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

# CSRNet output stride: density map is 1/8 of the input in each dimension.
OUTPUT_STRIDE = 8


class DensityModel(Protocol):
    stride: int

    def predict(self, tile_rgb: Image.Image) -> np.ndarray:
        """Return a 2D float density map; its sum approximates the head count."""
        ...


def _torch_available() -> bool:
    try:
        import torch  # noqa: F401

        return True
    except Exception:
        return False


def build_csrnet():
    """Construct the CSRNet module (requires torch)."""
    import torch
    import torch.nn as nn
    from torchvision import models

    class CSRNet(nn.Module):
        def __init__(self, load_vgg_frontend: bool = True):
            super().__init__()
            # Frontend = VGG16 features up to conv4_3 (first 10 conv layers).
            frontend_cfg = [64, 64, "M", 128, 128, "M", 256, 256, 256, "M", 512, 512, 512]
            self.frontend = _make_vgg_layers(frontend_cfg, in_channels=3)
            # Backend = dilated convolutions.
            backend_cfg = [512, 512, 512, 256, 128, 64]
            self.backend = _make_vgg_layers(backend_cfg, in_channels=512, dilation=2)
            self.output_layer = nn.Conv2d(64, 1, kernel_size=1)
            if load_vgg_frontend:
                self._init_frontend_from_vgg16()

        def forward(self, x):
            x = self.frontend(x)
            x = self.backend(x)
            x = self.output_layer(x)
            return x

        def _init_frontend_from_vgg16(self):
            try:
                vgg = models.vgg16(weights=models.VGG16_Weights.IMAGENET1K_V1)
            except Exception:
                vgg = models.vgg16(pretrained=False)
            src = list(vgg.features.state_dict().items())
            dst = self.frontend.state_dict()
            keys = list(dst.keys())
            for i, k in enumerate(keys):
                if i < len(src):
                    dst[k] = src[i][1]
            self.frontend.load_state_dict(dst)

    def _make_vgg_layers(cfg, in_channels, dilation=1):
        layers = []
        d = dilation
        for v in cfg:
            if v == "M":
                layers.append(nn.MaxPool2d(kernel_size=2, stride=2))
            else:
                conv = nn.Conv2d(in_channels, v, kernel_size=3, padding=d, dilation=d)
                layers += [conv, nn.ReLU(inplace=True)]
                in_channels = v
        return nn.Sequential(*layers)

    return CSRNet


class CSRNet:
    """Inference wrapper around the CSRNet torch module."""

    stride = OUTPUT_STRIDE

    def __init__(self, weights_path: Optional[str] = None, device: Optional[str] = None):
        import torch

        self._torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        net_cls = build_csrnet()
        # If we have trained weights, skip downloading VGG init.
        self.net = net_cls(load_vgg_frontend=weights_path is None)
        if weights_path:
            state = torch.load(weights_path, map_location="cpu")
            if isinstance(state, dict) and "state_dict" in state:
                state = state["state_dict"]
            state = { _strip_prefix(k): v for k, v in state.items() }
            self.net.load_state_dict(state, strict=False)
        self.net.to(self.device).eval()

    def predict(self, tile_rgb: Image.Image) -> np.ndarray:
        torch = self._torch
        arr = np.asarray(tile_rgb.convert("RGB"), dtype=np.float32) / 255.0
        arr = (arr - IMAGENET_MEAN) / IMAGENET_STD
        tensor = torch.from_numpy(arr.transpose(2, 0, 1)).unsqueeze(0).to(self.device)
        with torch.no_grad():
            out = self.net(tensor)
        return out.squeeze().detach().cpu().numpy().astype(np.float32)


def _strip_prefix(key: str) -> str:
    for p in ("module.", "model."):
        if key.startswith(p):
            return key[len(p):]
    return key


def load_csrnet(weights_path: Optional[str] = None, device: Optional[str] = None) -> CSRNet:
    return CSRNet(weights_path=weights_path, device=device)


def load_model(weights_path: Optional[str] = None, device: Optional[str] = None) -> DensityModel:
    """Best available model: CSRNet if possible, else the heuristic fallback."""
    from fallback import FallbackModel

    if weights_path and not _torch_available():
        print(
            "[crowd-counter] WARNING: weights given but torch is not installed. "
            "Using fallback estimator. `pip install torch` to run CSRNet.",
            file=sys.stderr,
        )
        return FallbackModel()

    if _torch_available():
        try:
            model = load_csrnet(weights_path=weights_path, device=device)
            tag = "trained weights" if weights_path else "ImageNet frontend only (UNTRAINED head -> counts meaningless)"
            print(f"[crowd-counter] Using CSRNet ({tag}) on {model.device}.", file=sys.stderr)
            return model
        except Exception as exc:  # pragma: no cover - environment dependent
            print(f"[crowd-counter] CSRNet load failed ({exc}); using fallback.", file=sys.stderr)
            return FallbackModel()

    print(
        "[crowd-counter] torch not installed -> using heuristic fallback estimator "
        "(NOT accurate). `pip install torch torchvision` for the real model.",
        file=sys.stderr,
    )
    return FallbackModel()
