"""Qwen2.5-VL 纯文本推理（无图像）。"""

from __future__ import annotations

from typing import TYPE_CHECKING, List

import torch

if TYPE_CHECKING:
    from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration


def load_qwen(model_path: str, device: str):
    from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration

    model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
        model_path,
        torch_dtype=torch.bfloat16,
        attn_implementation="eager",
    ).eval().to(device)
    processor = AutoProcessor.from_pretrained(
        model_path,
        trust_remote_code=True,
        padding_side="left",
        use_fast=True,
    )
    return model, processor


def generate_text(
    model: "Qwen2_5_VLForConditionalGeneration",
    processor: "AutoProcessor",
    system_prompt: str,
    user_prompt: str,
    device: str,
    max_new_tokens: int = 512,
    do_sample: bool = False,
    temperature: float = 0.7,
) -> str:
    try:
        from qwen_vl_utils import process_vision_info
    except ImportError as e:
        raise ImportError(
            "需要安装 qwen-vl-utils，例如: pip install qwen-vl-utils"
        ) from e

    messages = [
        {"role": "system", "content": [{"type": "text", "text": system_prompt}]},
        {"role": "user", "content": [{"type": "text", "text": user_prompt}]},
    ]
    text = processor.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    image_inputs, video_inputs = process_vision_info(messages)
    inputs = processor(
        text=[text],
        images=image_inputs,
        videos=video_inputs,
        padding=True,
        return_tensors="pt",
    )
    inputs = inputs.to(device)
    kwargs = dict(max_new_tokens=max_new_tokens, do_sample=do_sample)
    if do_sample:
        kwargs["temperature"] = temperature
    elif hasattr(model, "generation_config") and model.generation_config is not None:
        model.generation_config.temperature = None
    with torch.inference_mode():
        generated_ids = model.generate(**inputs, **kwargs)
    trimmed: List[int] = [
        out_ids[len(in_ids) :]
        for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
    ][0].tolist()
    return processor.decode(trimmed, skip_special_tokens=True).strip()
