# CT Adventure Deck — illustration set prompts

## How to use

1. Open ONE ChatGPT chat. Paste the style block below as your first message.
2. Then send each subject line as its own message, prefixed exactly: `Same exact style as the previous images: [subject line]`
3. Generate in the themed runs listed (outdoors → buildings → food/drink → events) — consistency holds best between adjacent generations.
4. Square 1024×1024. If one drifts off-style, regenerate immediately before moving on.
5. Save each as `{category}.png` using the filename in brackets. Drop them in the app's `data/img/` folder as `.webp` (or hand me the PNGs — I'll convert, crop, and compress).

---

## Style block (paste first, once)

> I'm going to ask you for a series of 26 illustrations. Every one must follow this exact locked style, with zero drift:
>
> Flat vector travel poster illustration in vintage WPA national park poster style. Strict limited palette, ONLY these colors: cream #F5EFDC, paper #E8DFC4, deep forest green #1F4D3A, mid green #2C6B4F, burnt orange #C75B2B, mustard gold #D9A441, dark navy ink #1E2A44. Bold simplified silhouettes, layered flat shapes, subtle paper-grain texture, low golden sun, long soft shadows. New England / Connecticut scenery. No text, no words, no lettering, no borders, no frames, no logos. No human faces (tiny distant figures are fine). Square 1:1 composition with a clear focal subject, calm and warm mood.
>
> Confirm you've got the style locked, then I'll send subjects one at a time.

---

## Run 1 — outdoors

1. `[hike]` A winding dirt trail up a forested traprock ridge to a small stone observation tower at the summit, rolling hills behind
2. `[park]` A grand old oak tree beside a bench on a small-town New England green, low sun through the branches
3. `[garden]` A rose garden in full bloom with a wooden arch arbor and gravel path
4. `[beach]` A quiet Long Island Sound beach with a striped umbrella, dune grass, and a long wooden jetty
5. `[water]` A canoe gliding on a calm river between wooded banks, paddle mid-stroke, ripples trailing
6. `[lighthouse]` A white New England lighthouse with a navy lantern room on a rocky point, gulls overhead
7. `[farm]` A red barn with a white silo behind a split-rail fence, pumpkins by the roadside stand
8. `[kids]` A red diamond kite on a long tail flying over a grassy hilltop, string running down out of frame

## Run 2 — buildings & places

9. `[museum]` A grand columned museum facade with wide stone steps and banners-free pediment, late afternoon light
10. `[history]` A colonial saltbox house with a stone wall and a tall flagpole, autumn trees
11. `[theater]` A vintage theater marquee glowing at dusk with sweeping curtains visible through the doors
12. `[lodging]` A cozy country inn at dusk, warm windows lit, rocking chairs on the porch
13. `[shopping]` A small-town main street storefront with a striped awning and a bicycle leaning outside
14. `[family]` An old-fashioned carousel with painted horses under a striped canopy roof
15. `[generic]` A winding country road through rolling Connecticut hills toward a distant white church steeple

## Run 3 — food & drink

16. `[restaurant]` A bistro table set for two by a window, wine glasses and a candle, evening glow
17. `[cafe]` A corner coffee shop counter with a steaming mug and a glass pastry case
18. `[brewery]` Two full beer glasses on a taproom bar with copper brew kettles behind
19. `[winery]` Vineyard rows on a hillside with a rustic tasting barn and a single wine glass on a barrel in the foreground
20. `[food-drink]` A long farm table spread with shared dishes under string lights at golden hour

## Run 4 — events

21. `[live-music]` An outdoor bandstand stage at dusk with a silhouetted guitarist and glowing string lights
22. `[festival]` A fairground with triangle bunting, striped tents, and a small ferris wheel on the horizon
23. `[market]` A farmers market stall with crates of tomatoes, corn, and flowers under a green canopy
24. `[art]` An easel with a half-finished landscape painting in a sunlit gallery space
25. `[sports]` A small-town ballpark at golden hour with a pennant flag flying over the grandstand
26. `[holiday]` A town green at night with a giant lit tree, falling snow, and warm shop windows

---

## After generating

Name files `hike.webp`, `park.webp`, etc. (exact category in brackets), drop into `data/img/`.
The app already prefers these images and falls back to the built-in SVG art for any that are missing —
partial sets are fine, nothing breaks.
