# Reverse-engineering an object from a photo

The photo is **evidence**. `jobs/<slug>/spec.json` is where the evidence is
written down: every number the model uses is `measured` off a photo, given by
the `user`, or `assumed` with a reason, and a measured one keeps its pixels and
the reference it was scaled from. The model reads `params["dims"]` and holds no
number of its own.

The photo has to be a file. If the user pasted one, ask for its path.

## 1. Scale each photo

Every view needs a known length in the same plane as the object: a bank card
(`card`), a coin (`euro-1`, `us-quarter`, ...), an A4 sheet, a ruler (`--ref 100`),
or one dimension of the object the user tells you (`--ref 42`, points across that
feature). With none in the photo, this is the one question you ask.

```bash
print3d grid photo.jpg                               # whole photo, labelled in pixels
print3d grid photo.jpg --crop 120,340,260,420        # zoom on one end of the reference
print3d measure <slug> scale front photo.jpg --ref card --points x1,y1,x2,y2
```

Read every point off a **crop**. At full size a pixel guess is millimetres
wrong; the crop's labels are photo pixels, so what you read goes straight into
`--points`.

**Taken at an angle** (most photos are): rectify instead. Pick the four corners
of a flat face of known size, in the order they should appear square-on
(top-left, top-right, bottom-right, bottom-left):

```bash
print3d meet x1,y1,x2,y2 x3,y3,x4,y4                  # a corner hidden behind something
print3d measure <slug> rectify top photo.jpg --corners x,y,x,y,x,y,x,y --size 31.8,15.8
print3d grid jobs/<slug>/views/top.png --crop ...     # read every later point off this
```

For a hidden corner, find two points on each edge that meets there and let
`meet` cross them; on a plain background, the lowest points of the outline
between bumps are where an edge shows through. Only what lies in the rectified
face measures true: anything standing off it, like a stud or a boss, smears
with the viewing angle. Measure such features where they meet the face, and
derive the rest from symmetry or record it as assumed.

View names `front back left right top bottom` set the camera axes in the part
**as printed** (z up off the bed). When the part prints in another pose, such
as a bracket laid on its side, pass `--look` and `--up` in the printed frame.

## 2. Measure the driving dimensions

```bash
print3d measure <slug> dim width --view front --points x1,y1,x2,y2
print3d measure <slug> dim depth --mm 15 --source assumed --why "back not photographed"
print3d measure <slug> unknown "wall thickness: no section visible"
```

Each measurement comes back with `tolerance_mm`. When it is wider than the part
can afford, crop tighter, or ask for a closer photo with the reference beside
the feature.

## 3. Outline each view

Trace the object's outer boundary in photo pixels: corners first, then enough
points along curves to follow them (8 to 30 points).

```bash
print3d measure <slug> outline front --points x,y,x,y,...
print3d measure <slug> outline top --mask top_mask.png   # white or opaque object, photo-sized
```

A traced outline closes through-holes; a mask keeps them. Use a mask when the
holes matter to the shape.

## 4. Model from the spec

Write `model.py` from `params["dims"]["<name>"]`. The run then adds a
`likeness` note per outlined view: the STL projected along that view and laid
over the photo. It is a defect like `overhang`:

| fix says | do |
| --- | --- |
| matches better seen with look=... up=... | rotate the part, or correct the view's `--look/--up` |
| shape is right, size is not | change the named driving dimension, or re-measure it |
| look at the overlay | open `jobs/<slug>/likeness/<view>.png`: red is in the photo and missing from the model, blue is model the photo does not show |

Read the overlay PNG even when the note is green.

## Parts that fit something

A knob on a shaft, a cap on a bottle, a clip on a rail: the mating dimension
decides whether the part works, and a photo resolves it to a millimetre at
best. Make a **coupon** first: a second job with only the mating feature, a few
millimetres tall. The user prints it and tries it on; record what they report
with `dim <name> --mm N --source user`, then build the full part.

## Done when

Every dimension `model.py` reads is in `spec.json` with a source, every
photographed view has a scale and an outline, and no `likeness` note is at
`error`. In the hand-off, list which dimensions are measured, given or assumed,
and the unknowns: those are what the user checks first on the printed part.
