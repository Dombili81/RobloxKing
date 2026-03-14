from PIL import Image
import os

class TemplateDesigner:
    def __init__(self):
        pass

    async def process_image(self, asset_path, template_path, output_dir="output", custom_filename=None):
        """
        Processes image merging locally using Pillow.
        Removing dependency on arena.site.
        """
        print(f"Processing local image merge: {os.path.basename(asset_path)} + {os.path.basename(template_path)}")
        
        try:
            # Open images
            asset_img = Image.open(asset_path).convert("RGBA")
            template_img = Image.open(template_path).convert("RGBA")
            
            # Ensure they are same size
            # Usually Roblox templates are 585x559
            if asset_img.size != template_img.size:
                print(f"Resizing template from {template_img.size} to match asset {asset_img.size}")
                template_img = template_img.resize(asset_img.size, Image.Resampling.LANCZOS)
            
            # Merge logic: Template is usually an overlay (logo/frame) on the Asset
            # Using alpha_composite to respect transparency
            # Result = Asset background + Template overlay
            combined = Image.alpha_composite(asset_img, template_img)
            
            # Generate output path
            if custom_filename:
                final_filename = custom_filename
                if not final_filename.lower().endswith(".png"):
                    final_filename += ".png"
            else:
                base_name = os.path.basename(asset_path)
                name_root, _ = os.path.splitext(base_name)
                final_filename = f"{name_root}_designed.png"
                
            output_path = os.path.join(output_dir, final_filename)
            
            os.makedirs(output_dir, exist_ok=True)
            combined.save(output_path, "PNG")
            
            print(f"Local merge complete. Saved to: {output_path}")
            return output_path
            
        except Exception as e:
            print(f"Error in local image processing: {e}")
            return None
