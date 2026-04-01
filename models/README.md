# AI Detection Models

Place your YOLO models here for AI detection functionality.

## Required Models

1. **defect_model.pt** - For product defect detection
   - Trained to detect various product defects (scratches, dents, cracks, etc.)
   
2. **box_model.pt** - For packaging verification
   - Must detect: `box`, `tape`, `receipt` (or `paper`/`invoice`)
   - Used to verify complete packaging before shipping
   
3. **accessory_model.pt** - For accessory completeness check
   - Trained to detect common accessories: manual, warranty, cable, adapter, remote, battery
   - Reports missing accessories

## Model Format

- Models should be in YOLO format (.pt files)
- Compatible with ultralytics library
- Recommended: YOLOv8 or YOLOv5

## Training Your Models

1. Collect images of your products/packaging
2. Label with appropriate classes
3. Train using ultralytics:

```python
from ultralytics import YOLO

# For defect detection
model = YOLO('yolov8n.pt')  # Load pretrained
model.train(data='defect_dataset.yaml', epochs=100)
model.export(format='pt')

# Similar for box and accessory models
```

## Demo Mode

If models are not present, the system runs in demo mode with simulated results.
