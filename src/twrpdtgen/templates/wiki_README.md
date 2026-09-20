## Now that you have a device tree for your device, it's time to build a TWRP recovery image

### Clone minimal TWRP environment
* Follow the instructions in this page:

`https://github.com/minimal-manifest-twrp/platform_manifest_twrp_omni`

Remember to clone the correct version of TWRP based on what Android version your phone has! If your phone has Android 8.0, clone the twrp-8.0 branch.

### Move device tree to TWRP sources
* Copy `working/(brand)/(device)` folder to `device/(brand)/(device)` folder in TWRP sources

Example: 
- brand name: xiaomi
- device codename: whyred
* Copy `working/xiaomi/whyred` to `device/xiaomi/whyred` in TWRP sources

### Building
* Open a terminal with the current dir pointing to the TWRP sources root
* Then initialize the environment:
```bash
. build/envsetup.sh
```
* After that, run:
```bash
lunch twrp_codename-eng
```
(where `codename` is the codename of your phone)
* If that is successful, build the recovery:
```bash
mka recoveryimage
```

If your device is A/B, use instead:
```bash
mka bootimage
```
* Once complete, you will find your recovery.img in `out/target/product/codename/`.
