import React from "react";
import {Composition, registerRoot} from "remotion";
import {PresentationVideo} from "./PresentationVideo";
import {PresentationPropsSchema, presentationFrames, type PresentationProps} from "./presentation-types";

const defaults: PresentationProps = {title: "PPT讲解", audioSrc: null,
  slides: [{number: 1, title: "预览", imageSrc: "slide-01.png", durationInFrames: 90, captions: []}]};
registerRoot(() => <Composition id="PresentationVideo" component={PresentationVideo}
  width={1920} height={1080} fps={30} durationInFrames={90}
  schema={PresentationPropsSchema} defaultProps={defaults}
  calculateMetadata={({props}) => ({durationInFrames: presentationFrames(props)})} />);
