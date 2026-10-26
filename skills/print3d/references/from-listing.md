# Replacing something sold in a shop

The user wants a part they would otherwise buy, and usually does not have it in
hand. The shop listing stands in for the object: its **stated dimensions** are
evidence, like a ruler in the photo, and its **product photos** are the views.
Everything else works as in `references/from-photo.md`; read that first.

The listing is a URL or a product name. Fetch the page yourself. If it blocks
you, ask the user to paste the dimensions and save the photos to files.

## 1. Record the product

```bash
print3d measure <slug> listing <url> --name "Wall hook, brushed steel" --price 4.99 --currency EUR
```

The price is what the printed part is weighed against in the hand-off.

## 2. Quote every stated dimension

Copy each dimension the listing gives, with the listing's own words as `--quote`.
A spec table, a dimensioned drawing and the description all count. Reviews and
"customers also bought" do not.

```bash
print3d measure <slug> dim length --mm 120 --source listing --quote "Dimensions: 120 x 45 x 30 mm"
print3d measure <slug> dim hole_spacing --mm 64 --source listing --quote "Hole centres: 64 mm"
print3d measure <slug> dim height --mm 50 --source listing --quote "Height: 5 cm" --tolerance 5
```

`--tolerance` is how coarsely the listing rounds: 0.5 mm by default (whole
millimetres), 5 for centimetres, 12.7 for half inches. Convert inches to mm, and
keep the inch figure in the quote.

**Check the dimensions belong to the product, not the box.** "Package
dimensions" and "shipping weight" describe the carton. When the listed
dimensions disagree with the photo's proportions by more than their rounding,
record the mismatch with `unknown` and ask the user which to trust.

## 3. Scale each product photo from a listed dimension

Save the product photos to files. Pick the views that are closest to square-on:
a plain side, front or top, not the lifestyle shot at an angle. Then scale each
one from a listed dimension that lies in the photo's plane:

```bash
print3d grid hook-side.jpg --crop ...
print3d measure <slug> scale front hook-side.jpg --ref dim:length --points x1,y1,x2,y2
```

`dim:<name>` takes the length from the spec, and its rounding is carried into
every tolerance measured off that view. Scale from the **longest** listed
dimension the photo shows: its rounding costs the least as a ratio. A photo with
no listed dimension in its plane can still be rectified (`measure rectify`) from
a face whose two sides are both listed.

## 4. Measure what the listing does not say

The listing gives a few overall sizes. Everything else the model needs (a wall
thickness, a hook's radius, a hole's position) is measured off the scaled
photos as in `from-photo.md` step 2. Outline each photo for the likeness check.

Then score the scale before trusting it: **measure a second listed dimension
off the photo** under a different name (`length_measured`), and compare. When
the two disagree by more than both tolerances together, the photo is in
perspective or shows another variant; use a different photo, or rectify.

When they agree, model from the **tighter** of the two. A listing that says
"12 cm" allows 115 to 125 mm; a photo scaled from a 200 mm leg may pin it to
127 ± 4. Have `model.py` read the measured name, and say why in a comment.

## 5. What a shop part has that a print does not

Record each with `unknown` so the hand-off names it:

- Metal parts: springs, screws, magnets, pins. Say what to buy ("M4 x 12 screw",
  "6 x 3 mm magnet") instead of printing them.
- Loads the original carries by material: a steel hook holding a coat, a shelf
  bracket. A PLA copy at the same section is weaker; thicken it and say so.
- Mating parts: a knob's shaft, a cap's thread, a clip's rail. The listing
  rarely gives them to the tenth of a millimetre. Make the coupon described in
  `from-photo.md` first.

## Not for copying

Make replacements and repairs for the user's own use. Leave brand names and
logos off the model, and decline safety-critical parts (child seats, climbing
gear, anything holding a person or a load overhead) whatever the listing says.

## Done when

As in `from-photo.md`, plus: the listing is recorded, every dimension the shop
states is quoted, each photo is scaled from one of them, and a second listed
dimension was measured back off the photo within tolerance. In the hand-off,
put the print's grams and time beside the listing's price, and list what is
listed, measured and assumed.
