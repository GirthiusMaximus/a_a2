import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { api } from "../api";

interface Props {
  jobId: string;
  exaggeration: number;
}

async function loadImageData(url: string, maxSize: number): Promise<ImageData> {
  const img = new Image();
  img.crossOrigin = "anonymous";
  await new Promise<void>((res, rej) => {
    img.onload = () => res();
    img.onerror = () => rej(new Error(`failed to load ${url}`));
    img.src = url;
  });
  const size = Math.min(maxSize, img.width);
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d")!;
  ctx.drawImage(img, 0, 0, size, size);
  return ctx.getImageData(0, 0, size, size);
}

export default function Viewer3D({ jobId, exaggeration }: Props) {
  const mountRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;
    let disposed = false;
    let renderer: THREE.WebGLRenderer | null = null;
    let frame = 0;

    (async () => {
      // height_rgb.png packs 16-bit height into R (hi) + G (lo), north-up
      const heightData = await loadImageData(api.artifactUrl(jobId, "height_rgb.png"), 513);
      if (disposed) return;

      const res = heightData.width;
      const segments = res - 1;
      const planeSize = 100;

      const scene = new THREE.Scene();
      scene.background = new THREE.Color(0x10151a);
      scene.fog = new THREE.Fog(0x10151a, 220, 420);

      const camera = new THREE.PerspectiveCamera(
        55, mount.clientWidth / mount.clientHeight, 0.1, 1000);
      camera.position.set(0, 55, 85);

      renderer = new THREE.WebGLRenderer({ antialias: true });
      renderer.setSize(mount.clientWidth, mount.clientHeight);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      mount.appendChild(renderer.domElement);

      const controls = new OrbitControls(camera, renderer.domElement);
      controls.enableDamping = true;
      controls.maxPolarAngle = Math.PI / 2.05;
      controls.minDistance = 10;
      controls.maxDistance = 320;

      // terrain: heights are normalized*1000m - 500m (sea = 0)
      const geo = new THREE.PlaneGeometry(planeSize, planeSize, segments, segments);
      geo.rotateX(-Math.PI / 2);
      const pos = geo.attributes.position as THREE.BufferAttribute;
      // world meters -> scene units; PlaneGeometry row 0 = -z... our image row 0 = north
      const d = heightData.data;
      let mapMeters = 3000;
      for (let row = 0; row <= segments; row++) {
        for (let col = 0; col <= segments; col++) {
          const i = row * (segments + 1) + col;
          const px = (row * res + col) * 4;
          const h01 = (d[px] * 256 + d[px + 1]) / 65535;
          const meters = h01 * 1000 - 500;
          pos.setY(i, meters);
        }
      }
      // read map size from stats via dataset attribute? use artifact recipe instead
      try {
        const job = await api.job(jobId);
        mapMeters = (job.recipe?.size as number) || 3000;
      } catch { /* default */ }
      const metersToUnits = planeSize / mapMeters;
      for (let i = 0; i < pos.count; i++) {
        pos.setY(i, pos.getY(i) * metersToUnits * exaggeration);
      }
      pos.needsUpdate = true;
      geo.computeVertexNormals();

      const texture = new THREE.TextureLoader().load(api.artifactUrl(jobId, "preview.png"));
      texture.colorSpace = THREE.SRGBColorSpace;
      texture.anisotropy = 4;
      const mat = new THREE.MeshStandardMaterial({
        map: texture, roughness: 0.95, metalness: 0.0,
      });
      const terrain = new THREE.Mesh(geo, mat);
      scene.add(terrain);

      // water plane at sea level (0)
      const waterMat = new THREE.MeshStandardMaterial({
        color: 0x1d4e5f, transparent: true, opacity: 0.82,
        roughness: 0.25, metalness: 0.1,
      });
      const water = new THREE.Mesh(
        new THREE.PlaneGeometry(planeSize * 1.6, planeSize * 1.6), waterMat);
      water.rotateX(-Math.PI / 2);
      water.position.y = 0.02;
      scene.add(water);

      const sun = new THREE.DirectionalLight(0xfff2dd, 2.2);
      sun.position.set(0.95, 2.87, 2.37).normalize().multiplyScalar(100);
      scene.add(sun);
      scene.add(new THREE.AmbientLight(0x8899aa, 0.8));

      const onResize = () => {
        if (!renderer) return;
        camera.aspect = mount.clientWidth / mount.clientHeight;
        camera.updateProjectionMatrix();
        renderer.setSize(mount.clientWidth, mount.clientHeight);
      };
      window.addEventListener("resize", onResize);

      const animate = () => {
        if (disposed || !renderer) return;
        frame = requestAnimationFrame(animate);
        controls.update();
        renderer.render(scene, camera);
      };
      animate();

      return () => window.removeEventListener("resize", onResize);
    })();

    return () => {
      disposed = true;
      cancelAnimationFrame(frame);
      if (renderer) {
        renderer.dispose();
        renderer.domElement.remove();
        renderer = null;
      }
    };
  }, [jobId, exaggeration]);

  return <div ref={mountRef} style={{ width: "100%", height: "100%", minHeight: 420 }} />;
}
