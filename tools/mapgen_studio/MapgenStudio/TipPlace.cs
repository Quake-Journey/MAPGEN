using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives.PopupPositioning;
using Avalonia.Input;
using Avalonia.Interactivity;

namespace MapgenStudio;

/// <summary>
/// Every tooltip of the Studio placed as Avalonia places it - under the pointer and to its right, 20 below it - but
/// ABOVE the pointer, never over it, when it does not fit under it.
///
/// The PO, 06.11 (and 07.10 before): «кнопка запуска генерации срабатывает только со второго-третьего нажатия». His
/// Studio's own record of the start button (ui_clicks.txt) showed it every time: a first press with «released» and no
/// «pressed» - the press went to something over the button. Avalonia 12.1.3 places a tooltip by the pointer (a 1 x 1
/// anchor, offset 0,20); near the screen's foot it does not fit under the pointer and the positioner flips it above -
/// keeping the +20 (ManagedPopupPositioner: «the offset is not negated») - so its lowest 20 units lie under the
/// pointer. A tooltip is a window of its own and takes the press; it closes, the release lands on the button: no
/// click. The start button stands at the page's foot, at the screen's foot on a maximised window - every first press
/// after the tooltip had shown. Here the pointer is the anchor 22 units tall (2 over it .. 20 under it, no offset): a
/// flip puts the tooltip's foot 2 over the pointer.
/// </summary>
public static class TipPlace
{
    /// <summary>The pointer's last place on the screen (any window of the Studio).</summary>
    internal static PixelPoint? LastScreen;

    /// <summary>The 3.55 placement (Avalonia's own for a pointer), for the window test's RED only.</summary>
    internal static bool Old;

    public static void Install()
    {
        // every control that gets a tooltip gets this placement - the Studio sets tips in many places (Ui.Tip, SetTip)
        ToolTip.TipProperty.Changed.AddClassHandler<Control>((c, e) =>
        {
            if (e.NewValue == null)
                return;
            ToolTip.SetPlacement(c, PlacementMode.Custom);
            ToolTip.SetCustomPopupPlacementCallback(c, Place);
        });
        InputElement.PointerMovedEvent.AddClassHandler<TopLevel>((top, e) =>
        {
            try
            {
                LastScreen = top.PointToScreen(e.GetPosition(top));
            }
            catch (Exception)
            {
                // a window closing: the next move says it again
            }
        }, RoutingStrategies.Tunnel | RoutingStrategies.Bubble, handledEventsToo: true);
    }

    /// <summary>The placement: the anchor is the pointer (its screen place made the target's root coordinates).</summary>
    public static void Place(CustomPopupPlacement p)
    {
        var at = Pointer(p);
        if (at == null)
        {
            // no pointer known (a tooltip opened without a move): under the control, above it when it does not fit
            p.Anchor = PopupAnchor.Bottom;
            p.Gravity = PopupGravity.Bottom;
            p.Offset = new Point(0, 4);
            p.ConstraintAdjustment = PopupPositionerConstraintAdjustment.FlipY | PopupPositionerConstraintAdjustment.SlideX
                                     | PopupPositionerConstraintAdjustment.FlipX | PopupPositionerConstraintAdjustment.ResizeY;
            return;
        }
        var (x, y) = (at.Value.X, at.Value.Y);
        if (Old)
        {
            p.AnchorRectangle = new Rect(x, y, 1, 1);
            p.Anchor = PopupAnchor.TopLeft;
            p.Gravity = PopupGravity.BottomRight;
            p.Offset = new Point(0, 20);
            p.ConstraintAdjustment = PopupPositionerConstraintAdjustment.All;
            return;
        }
        p.AnchorRectangle = new Rect(x, y - 2, 1, 22);
        p.Anchor = PopupAnchor.BottomLeft;
        p.Gravity = PopupGravity.BottomRight;
        p.Offset = default;
        // no vertical slide: a slide is what may push a tooltip back over the pointer
        p.ConstraintAdjustment = PopupPositionerConstraintAdjustment.FlipY | PopupPositionerConstraintAdjustment.ResizeY
                                 | PopupPositionerConstraintAdjustment.FlipX | PopupPositionerConstraintAdjustment.SlideX;
    }

    /// <summary>The pointer in the coordinates the positioner was given the target's rectangle in.</summary>
    private static Point? Pointer(CustomPopupPlacement p)
    {
        if (LastScreen is not { } screen || p.Target is not Visual target || target.Bounds.Width <= 0 || target.Bounds.Height <= 0)
            return null;
        try
        {
            var local = target.PointToClient(screen);
            var r = p.AnchorRectangle;          // the target's own rectangle, in the root's coordinates
            return new Point(r.X + local.X * r.Width / target.Bounds.Width, r.Y + local.Y * r.Height / target.Bounds.Height);
        }
        catch (Exception)
        {
            return null;
        }
    }
}
